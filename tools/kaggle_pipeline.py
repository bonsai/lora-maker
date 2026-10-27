#!/usr/bin/env python3
"""CLI/CD orchestrator for the private SDXL LoRA training on Kaggle.

Workflow 05 is the policy source. This tool is the only place that performs
remote side effects, and it does so only with --execute:

    doctor   read-only diagnosis (auth, dataset approval, quota, remote state)
    build    render the kernel bundle in build/kaggle-lora (no network)
    dataset  create / version the private Kaggle dataset (needs --execute)
    train    push the kernel and start training (needs --execute)
    wait     poll until the kernel reaches a terminal state
    logs     download the training log
    fetch    download the kernel output (LoRA + summary) into dist/lora
    run      the whole chain with the same gates

Design rules:
  * private only; public visibility is never selectable here
  * dataset approval hashes must match the ZIP before any upload
  * credentials are read by the Kaggle CLI itself and are never printed
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_workflow as rw  # noqa: E402

POLICY_PATH = ROOT / "workflows/05-lora-training.yml"
RUNS = ROOT / "runs"
KAGGLE_RUNS = RUNS / "kaggle"
EVENT_LOG = RUNS / "events.jsonl"
BUILD = ROOT / "build/kaggle-lora"
DATASET_STAGE = ROOT / "build/kaggle-dataset"
TRAIN_IMAGE_DIR = "/kaggle/temp/train/1_yamazaki_shishi"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

KERNEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,49}/[a-z0-9][a-z0-9-]{1,49}$")
STATUS_RE = re.compile(r"KernelWorkerStatus\.([A-Z_]+)")
SECRET_RE = re.compile(r"(KGAT_[A-Za-z0-9_\-]+|Bearer\s+[A-Za-z0-9._\-]+)")
TERMINAL_OK = {"COMPLETE"}
TERMINAL_BAD = {"ERROR", "CANCEL_ACKNOWLEDGED", "CANCEL_REQUESTED"}
TERMINAL = TERMINAL_OK | TERMINAL_BAD


# ---------------------------------------------------------------- primitives


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def log_event(name: str, status: str, **details) -> None:
    EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": name,
        "status": status,
        **details,
    }
    with EVENT_LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def receipt(name: str, payload: dict) -> Path:
    path = KAGGLE_RUNS / f"{name}.json"
    write_json(path, payload)
    return path


def redact(text: str) -> str:
    """Remove anything that looks like a Kaggle credential before printing/logging."""
    cleaned = SECRET_RE.sub("[redacted]", text)
    for variable in ("KAGGLE_KEY", "KAGGLE_API_TOKEN"):
        value = os.environ.get(variable)
        if value and len(value) > 3:
            cleaned = cleaned.replace(value, "[redacted]")
    return cleaned


def run_cli(command: list[str], cwd: Path | None = None, timeout: int = 300) -> str:
    process = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    output = redact((process.stdout or "") + (process.stderr or "").strip())
    if process.returncode != 0:
        raise RuntimeError(f"command failed ({process.returncode}): {' '.join(command)}\n{output}".strip())
    return output


def kaggle(args: list[str], timeout: int = 300) -> str:
    return run_cli([sys.executable, "-m", "kaggle", *args], timeout=timeout)


def load_policy(path: Path = POLICY_PATH) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"missing workflow policy: {path}")
    policy = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    execution = policy.get("execution") or {}
    if execution.get("mode") != "dry_run":
        raise ValueError("workflow 05 must default to dry_run")
    kaggle_cfg = policy.get("kaggle") or {}
    if kaggle_cfg.get("is_private") is not True:
        raise ValueError("workflow 05 must pin the kernel to private")
    if kaggle_cfg.get("accelerator") != "NvidiaTeslaT4":
        raise ValueError("workflow 05 must pin the T4 accelerator for quota predictability")
    if kaggle_cfg.get("enable_internet") is not True:
        raise ValueError("sd-scripts and the SDXL base model need internet in the kernel")
    return policy


def kaggle_username(timeout: int = 60) -> str | None:
    try:
        output = kaggle(["config", "view"], timeout=timeout)
    except Exception:
        return None
    match = re.search(r"^-\s*username:\s*(\S+)\s*$", output, re.MULTILINE)
    return match.group(1) if match else None


def validate_kernel_id(kernel_id: str) -> str:
    if not KERNEL_ID_RE.match(kernel_id):
        raise ValueError(
            f"invalid kernel id {kernel_id!r}; expected lowercase '<owner>/<slug>' "
            "with 2-50 characters per part"
        )
    return kernel_id


def parse_status(text: str) -> str | None:
    match = STATUS_RE.search(text)
    return match.group(1) if match else None


def is_terminal(status: str | None) -> bool:
    return status in TERMINAL


def mask_visibility(value: dict) -> dict:
    """Defensive copy used by receipts so a remote payload cannot flip to public."""
    if value.get("isPrivate") is False:
        raise ValueError("remote dataset is public; refusing to continue")
    return value


# ---------------------------------------------------------------- dataset gate


def dataset_gate(
    zip_path: Path,
    approval_path: Path,
    summary_path: Path,
    root: Path = ROOT,
) -> dict:
    """Fail closed unless the approved dataset and the ZIP are byte-identical."""
    record, problems = rw.load_json_record(approval_path, "dataset review")
    if record is None:
        raise RuntimeError(problems[0] if problems else "dataset approval is missing")
    problems = list(problems) + rw.validate_dataset_approval(record)
    if problems:
        raise RuntimeError("dataset approval is incomplete:\n  - " + "\n  - ".join(problems))
    if not zip_path.is_file():
        raise FileNotFoundError(f"dataset ZIP missing: {zip_path}")

    zip_sha = sha256_file(zip_path)
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("sha256") and summary["sha256"] != zip_sha:
            raise RuntimeError(
                "ZIP SHA-256 no longer matches runs/summary.json; re-package and re-approve"
            )

    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        if "manifest.json" not in names:
            raise RuntimeError("ZIP has no manifest.json")
        manifest_bytes = archive.read("manifest.json")
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        rows = manifest.get("images") or []
        if not rows:
            raise RuntimeError("manifest.json contains no images")
        if hashlib.sha256(manifest_bytes).hexdigest() != record["manifest_sha256"]:
            raise RuntimeError("manifest.json changed after approval; re-review and re-approve")
        if manifest.get("content_sha256") != record["content_sha256"]:
            raise RuntimeError("approved content_sha256 does not match the ZIP manifest")
        if rw.content_digest(rows) != manifest.get("content_sha256"):
            raise RuntimeError("ZIP manifest content hash is inconsistent")

        expected = set()
        for row in rows:
            expected.add(f"images/{Path(str(row['image_path'])).name}")
            expected.add(f"images/{Path(str(row['caption_path'])).name}")
        actual = {name for name in names if name.startswith("images/") and not name.endswith("/")}
        if expected - actual:
            raise RuntimeError(f"ZIP is missing {len(expected - actual)} image/caption file(s)")
        if actual - expected:
            raise RuntimeError(f"ZIP has {len(actual - expected)} unmanifested image/caption file(s)")
        forbidden = [name for name in names if name.endswith(".mp4") or name.startswith("source_videos/")]
        if forbidden:
            raise RuntimeError(f"ZIP must not contain source media: {forbidden[:3]}")

    return {
        "zip": str(zip_path.relative_to(root)) if zip_path.is_relative_to(root) else str(zip_path),
        "sha256": zip_sha,
        "images": len(rows),
        "manifest_sha256": record["manifest_sha256"],
        "content_sha256": record["content_sha256"],
        "reviewed_at": record.get("reviewed_at"),
    }


# ---------------------------------------------------------------- rendering


def render_kernel_metadata(policy: dict, owner: str, kernel_id: str | None = None) -> dict:
    cfg = policy["kaggle"]
    identifier = validate_kernel_id(kernel_id or f"{owner}/{cfg['kernel_slug'].split('/')[-1]}")
    return {
        "id": identifier,
        "title": identifier.split("/")[-1],
        "code_file": "train_lora.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_tpu": False,
        "enable_internet": bool(cfg["enable_internet"]),
        "dataset_sources": [cfg["dataset_slug"]],
        "kernel_sources": [],
        "competition_sources": [],
        "model_sources": [],
    }


def render_dataset_toml(policy: dict, image_dir: str = TRAIN_IMAGE_DIR) -> str:
    training = policy["training"]
    resolution = training["resolution"]
    lines = [
        "[general]",
        "enable_bucket = true",
        f"min_bucket_reso = {int(training['min_bucket_reso'])}",
        f"max_bucket_reso = {int(training['max_bucket_reso'])}",
        f"bucket_reso_steps = {int(training['bucket_reso_steps'])}",
        "bucket_no_upscale = false",
        "",
        "[[datasets]]",
        f"batch_size = {int(training['batch_size'])}",
        f"resolution = [{int(resolution[0])}, {int(resolution[1])}]",
        "",
        "  [[datasets.subsets]]",
        f'  image_dir = "{image_dir}"',
        '  caption_extension = ".txt"',
        "",
    ]
    return "\n".join(lines)


def render_run_config(policy: dict, epochs: int | None = None, dim: int | None = None) -> dict:
    training = dict(policy["training"])
    if epochs is not None:
        training["max_train_epochs"] = int(epochs)
    if dim is not None:
        training["network_dim"] = int(dim)
    images = int(policy["expected"]["dataset_images"])
    steps = math.ceil(
        images
        * int(training["max_train_epochs"])
        / (int(training["batch_size"]) * int(training["gradient_accumulation_steps"]))
    )
    training["steps_expected"] = steps
    return {
        "schema_version": 1,
        "project": policy["project"]["name"],
        "base_model": policy["project"]["base_model"],
        "trigger_token": policy["project"]["trigger_token"],
        "output_name": training["output_name"],
        "sd_scripts": {
            "repo": policy["framework"]["repo"],
            "ref": policy["framework"]["ref"],
            "commit": policy["framework"]["commit"],
            "script": policy["framework"]["script"],
        },
        "training": training,
    }


def bundle_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_kernel(
    policy: dict,
    owner: str,
    kernel_id: str | None = None,
    epochs: int | None = None,
    dim: int | None = None,
    build_dir: Path = BUILD,
    source: Path | None = None,
) -> dict:
    metadata = render_kernel_metadata(policy, owner, kernel_id)
    if metadata["is_private"] is not True or metadata["enable_gpu"] is not True:
        raise RuntimeError("refusing to build a public or GPU-less kernel")

    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)

    source = source or (ROOT / "kaggle/train_lora.py")
    if not source.is_file():
        raise FileNotFoundError(f"training script missing: {source}")
    shutil.copy2(source, build_dir / "train_lora.py")
    (build_dir / "dataset.toml").write_text(render_dataset_toml(policy), encoding="utf-8")
    config = render_run_config(policy, epochs=epochs, dim=dim)
    write_json(build_dir / "run_config.json", config)
    write_json(build_dir / "kernel-metadata.json", metadata)

    result = {
        "kernel_id": metadata["id"],
        "build_dir": str(build_dir),
        "bundle_sha256": bundle_digest(build_dir),
        "dataset_sources": metadata["dataset_sources"],
        "epochs": config["training"]["max_train_epochs"],
        "network_dim": config["training"]["network_dim"],
        "steps_expected": config["training"]["steps_expected"],
        "config": config,
        "metadata": metadata,
    }
    return result


def stage_dataset(zip_path: Path, stage_dir: Path = DATASET_STAGE) -> Path:
    """Extract the approved ZIP into a private-dataset upload folder."""
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            target = (stage_dir / member).resolve()
            if not target.is_relative_to(stage_dir.resolve()):
                raise RuntimeError(f"refusing unsafe ZIP member: {member}")
        archive.extractall(stage_dir)
    return stage_dir


# ---------------------------------------------------------------- doctor


def doctor_checks(offline: bool = False, policy: dict | None = None) -> list[dict]:
    policy = policy or load_policy()
    checks: list[dict] = []

    def add(check_id: str, status: str, detail: str) -> None:
        checks.append({"id": check_id, "status": status, "detail": redact(detail)})

    add("python", "ok" if sys.version_info >= (3, 10) else "fail", sys.version.split()[0])

    try:
        gate = dataset_gate(
            ROOT / policy["kaggle"]["dataset_zip"],
            ROOT / "data/approvals/dataset-approval.json",
            RUNS / "summary.json",
        )
        add("dataset", "ok", f"{gate['images']} pairs / sha256 {gate['sha256'][:12]}...")
    except Exception as exc:  # noqa: BLE001 - reported, not fatal to the diagnosis
        add("dataset", "fail", str(exc))

    local_script = ROOT / "kaggle/train_lora.py"
    add("training_script", "ok" if local_script.is_file() else "fail", str(local_script.relative_to(ROOT)))

    if offline:
        add("kaggle_cli", "skip", "offline mode")
        add("auth", "skip", "offline mode")
        add("remote_dataset", "skip", "offline mode")
        add("quota", "skip", "offline mode")
        return checks

    try:
        version = kaggle(["--version"], timeout=60).strip().splitlines()[0]
        add("kaggle_cli", "ok", version)
    except Exception as exc:  # noqa: BLE001
        add("kaggle_cli", "fail", str(exc))
        return checks

    username = kaggle_username()
    add("auth", "ok" if username else "fail", f"username={username}" if username else "no active credentials")

    dataset_slug = policy["kaggle"]["dataset_slug"]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            kaggle(["datasets", "metadata", dataset_slug, "-p", tmp], timeout=120)
            metadata_files = list(Path(tmp).glob("*.json"))
            metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
        info = metadata.get("info", metadata)
        mask_visibility(info)
        add("remote_dataset", "ok", f"{dataset_slug} private={info.get('isPrivate')}")
    except Exception as exc:  # noqa: BLE001
        add("remote_dataset", "warn", f"{dataset_slug}: {exc}")

    try:
        output = kaggle(["quota", "--format", "csv"], timeout=60)
        remaining = None
        for line in output.splitlines():
            cells = [cell.strip() for cell in line.split(",")]
            if cells and cells[0] == "GPU" and len(cells) >= 3:
                remaining = float(cells[2].rstrip("h"))
        if remaining is None:
            add("quota", "warn", "GPU row not found")
        else:
            add("quota", "ok" if remaining >= 3 else "warn", f"GPU remaining {remaining:.2f}h")
    except Exception as exc:  # noqa: BLE001
        add("quota", "warn", str(exc))

    return checks


def cmd_doctor(args) -> int:
    policy = load_policy()
    checks = doctor_checks(offline=args.offline, policy=policy)
    failed = [check for check in checks if check["status"] == "fail"]
    for check in checks:
        print(f"[{check['status']:4}] {check['id']}: {check['detail']}")
    path = receipt(
        "doctor",
        {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "offline": args.offline,
            "checks": checks,
            "ok": not failed,
        },
    )
    log_event("lora_doctor", "error" if failed else "success", failed=len(failed))
    print(f"receipt: {path}")
    return 1 if failed else 0


# ---------------------------------------------------------------- commands


def cmd_build(args) -> int:
    policy = load_policy()
    owner = args.owner or kaggle_username()
    if not owner:
        raise RuntimeError("owner unknown; pass --owner or authenticate the Kaggle CLI")
    result = build_kernel(
        policy,
        owner=owner,
        kernel_id=args.kernel,
        epochs=args.epochs,
        dim=args.dim,
    )
    path = receipt(
        "build",
        {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "kernel_id": result["kernel_id"],
            "bundle_sha256": result["bundle_sha256"],
            "epochs": result["epochs"],
            "network_dim": result["network_dim"],
            "steps_expected": result["steps_expected"],
            "dataset_sources": result["dataset_sources"],
        },
    )
    log_event("lora_build", "success", kernel=result["kernel_id"], bundle=result["bundle_sha256"])
    print(f"built {result['build_dir']} for {result['kernel_id']}")
    print(f"steps expected: {result['steps_expected']} (dim {result['network_dim']})")
    print(f"receipt: {path}")
    return 0


def remote_dataset_refs(timeout: int = 120) -> set[str]:
    """List the account's private datasets without touching the staging folder."""
    process = subprocess.run(
        [sys.executable, "-m", "kaggle", "datasets", "list", "-m", "--format", "csv"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    text = redact((process.stdout or "") + (process.stderr or ""))
    refs: set[str] = set()
    for line in text.splitlines():
        ref = line.split(",", 1)[0].strip()
        if ref.count("/") == 1 and " " not in ref:
            refs.add(ref.lower())
    return refs


def cmd_dataset(args) -> int:
    policy = load_policy()
    slug = policy["kaggle"]["dataset_slug"]
    gate = dataset_gate(
        ROOT / policy["kaggle"]["dataset_zip"],
        ROOT / "data/approvals/dataset-approval.json",
        RUNS / "summary.json",
    )
    stage = stage_dataset(ROOT / policy["kaggle"]["dataset_zip"])
    metadata = {
        "title": slug.split("/")[-1],
        "id": slug,
        "licenses": [{"name": "other"}],
    }
    write_json(stage / "dataset-metadata.json", metadata)
    files = sorted(item.name for item in stage.iterdir())
    command = ["datasets", "version", "-p", str(stage), "-m", args.message or "lora pipeline sync"]
    if not args.execute:
        print(f"dry-run: {gate['images']} pairs staged at {stage} ({files})")
        print("would run: python -m kaggle " + " ".join(command) + "  (or datasets create if absent)")
        print("pass --execute to upload a new private version")
        return 0

    existing = slug.lower() in remote_dataset_refs()
    if existing:
        output = kaggle(command, timeout=1800)
    else:
        output = kaggle(
            ["datasets", "create", "-p", str(stage), "-r", "skip"],
            timeout=1800,
        )
    print(redact(output.strip()))
    path = receipt(
        "dataset",
        {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "dataset": policy["kaggle"]["dataset_slug"],
            "images": gate["images"],
            "zip_sha256": gate["sha256"],
            "updated": existing,
        },
    )
    log_event("lora_dataset_push", "success", dataset=policy["kaggle"]["dataset_slug"], updated=existing)
    print(f"receipt: {path}")
    return 0


def resolve_kernel(policy: dict, args) -> str:
    if args.kernel:
        return validate_kernel_id(args.kernel)
    owner = args.owner or kaggle_username()
    if not owner:
        raise RuntimeError("owner unknown; pass --owner or authenticate the Kaggle CLI")
    return validate_kernel_id(f"{owner}/{policy['kaggle']['kernel_slug'].split('/')[-1]}")


def cmd_train(args) -> int:
    policy = load_policy()
    kernel_id = resolve_kernel(policy, args)
    # Always rebuild so --epochs / --dim overrides can never ride along with a
    # stale run_config.json from an earlier invocation.
    build = build_kernel(
        policy,
        owner=kernel_id.split("/")[0],
        kernel_id=kernel_id,
        epochs=args.epochs,
        dim=args.dim,
    )
    timeout = int(args.timeout or policy["kaggle"]["kernel_timeout_seconds"])
    print(f"bundle {build['bundle_sha256'][:12]}... steps {build['steps_expected']} dim {build['network_dim']}")
    command = [
        "kernels",
        "push",
        "-p",
        str(BUILD),
        "--accelerator",
        policy["kaggle"]["accelerator"],
        "-t",
        str(timeout),
    ]
    if not args.execute:
        print(f"dry-run: would push {kernel_id} to {policy['kaggle']['accelerator']} (cap {timeout}s)")
        print("would run: python -m kaggle " + " ".join(command))
        print("pass --execute to start a GPU session")
        return 0
    output = kaggle(command, timeout=600)
    print(redact(output.strip()))
    path = receipt(
        "train",
        {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "kernel": kernel_id,
            "accelerator": policy["kaggle"]["accelerator"],
            "timeout_seconds": timeout,
        },
    )
    log_event("lora_kernel_push", "success", kernel=kernel_id)
    print(f"receipt: {path}")
    return 0


def kernel_status(kernel_id: str) -> str | None:
    try:
        output = kaggle(["kernels", "status", kernel_id], timeout=120)
    except Exception as exc:  # noqa: BLE001 - 404 means "never run"
        if "404" in str(exc) or "not found" in str(exc).lower():
            return None
        raise
    return parse_status(output)


def cmd_status(args) -> int:
    """Informational: only a failed kernel counts as an error here."""
    policy = load_policy()
    kernel_id = resolve_kernel(policy, args)
    status = kernel_status(kernel_id)
    print(f"{kernel_id}: {status or 'NOT_PUSHED'}")
    return 1 if status in TERMINAL_BAD else 0


def wait_for(policy: dict, kernel_id: str, timeout: int, interval: int) -> int:
    deadline = time.time() + timeout
    last = None
    while True:
        status = kernel_status(kernel_id)
        if status != last:
            print(f"{time.strftime('%H:%M:%S')} {kernel_id}: {status or 'NOT_PUSHED'}")
            last = status
        if status in TERMINAL:
            return 0 if status in TERMINAL_OK else 1
        if time.time() >= deadline:
            print(f"timeout after {timeout}s (status={status or 'NOT_PUSHED'}); it may still be running")
            return 1
        time.sleep(interval)


def cmd_wait(args) -> int:
    policy = load_policy()
    kernel_id = resolve_kernel(policy, args)
    timeout = int(args.timeout or policy["kaggle"]["wait_timeout_seconds"])
    interval = int(args.interval or policy["kaggle"]["poll_interval_seconds"])
    code = wait_for(policy, kernel_id, timeout, interval)
    path = receipt(
        "wait",
        {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "kernel": kernel_id,
            "status": kernel_status(kernel_id),
            "ok": code == 0,
        },
    )
    log_event("lora_wait", "success" if code == 0 else "error", kernel=kernel_id)
    print(f"receipt: {path}")
    return code


def cmd_logs(args) -> int:
    policy = load_policy()
    kernel_id = resolve_kernel(policy, args)
    output = kaggle(["kernels", "logs", kernel_id], timeout=600)
    path = KAGGLE_RUNS / f"{kernel_id.split('/')[-1]}-logs.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output, encoding="utf-8")
    tail = "\n".join(output.splitlines()[-40:])
    print(tail)
    print(f"log: {path}")
    return 0


def cmd_fetch(args) -> int:
    policy = load_policy()
    kernel_id = resolve_kernel(policy, args)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = ROOT / "dist/lora" / f"{kernel_id.split('/')[-1]}-{stamp}"
    target.mkdir(parents=True, exist_ok=True)
    output = kaggle(["kernels", "output", kernel_id, "-p", str(target)], timeout=1800)
    print(redact(output.strip()))
    models = sorted(target.rglob("*.safetensors"))
    if not models:
        raise RuntimeError(f"no .safetensors in the kernel output under {target}; check logs")
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "kernel": kernel_id,
        "path": str(target),
        "files": [
            {"name": str(path.relative_to(target)), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in models
        ],
    }
    path = receipt("fetch", payload)
    log_event("lora_fetch", "success", kernel=kernel_id, models=len(models))
    print(f"fetched {len(models)} model(s) into {target}")
    print(f"receipt: {path}")
    return 0


def cmd_run(args) -> int:
    policy = load_policy()
    if not args.offline:
        checks = doctor_checks(offline=False, policy=policy)
        for check in checks:
            print(f"[{check['status']:4}] {check['id']}: {check['detail']}")
        if any(check["status"] == "fail" for check in checks):
            raise RuntimeError("doctor found blocking problems; fix them or rerun with --offline")
    kernel_id = resolve_kernel(policy, args)
    build = build_kernel(
        policy,
        owner=kernel_id.split("/")[0],
        kernel_id=kernel_id,
        epochs=args.epochs,
        dim=args.dim,
    )
    print(f"built {build['build_dir']} (steps {build['steps_expected']})")

    if not args.execute:
        print("dry-run complete: doctor + build only")
        print(f"would push {kernel_id} and wait/fetch after --execute")
        return 0

    if args.push_dataset:
        forwarded = argparse.Namespace(execute=True, message="lora pipeline dataset refresh")
        code = cmd_dataset(forwarded)
        if code:
            return code

    train_args = argparse.Namespace(
        execute=True,
        kernel=kernel_id,
        owner=kernel_id.split("/")[0],
        epochs=args.epochs,
        dim=args.dim,
        timeout=args.timeout,
    )
    code = cmd_train(train_args)
    if code:
        return code
    code = wait_for(policy, kernel_id, timeout=int(args.wait_timeout), interval=int(args.interval))
    if code:
        print("training did not complete; run `logs` for the tail")
        return code
    return cmd_fetch(argparse.Namespace(kernel=kernel_id, owner=kernel_id.split("/")[0]))


# ---------------------------------------------------------------- entrypoint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI/CD for the private SDXL LoRA on Kaggle")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="read-only diagnosis")
    doctor.add_argument("--offline", action="store_true", help="skip every network check")
    doctor.set_defaults(func=cmd_doctor)

    build = sub.add_parser("build", help="render the kernel bundle (no network)")
    build.add_argument("--owner", help="Kaggle owner; defaults to the authenticated user")
    build.add_argument("--kernel", help="full kernel id <owner>/<slug>")
    build.add_argument("--epochs", type=int)
    build.add_argument("--dim", type=int)
    build.set_defaults(func=cmd_build)

    dataset = sub.add_parser("dataset", help="upload a new private dataset version")
    dataset.add_argument("--execute", action="store_true")
    dataset.add_argument("--message", help="dataset version message")
    dataset.set_defaults(func=cmd_dataset)

    train = sub.add_parser("train", help="push the kernel and start training")
    train.add_argument("--execute", action="store_true")
    train.add_argument("--owner")
    train.add_argument("--kernel")
    train.add_argument("--epochs", type=int)
    train.add_argument("--dim", type=int)
    train.add_argument("--timeout", type=int, help="kernel time cap in seconds")
    train.set_defaults(func=cmd_train)

    status = sub.add_parser("status", help="show the kernel status")
    status.add_argument("--owner")
    status.add_argument("--kernel")
    status.set_defaults(func=cmd_status)

    wait = sub.add_parser("wait", help="poll until a terminal state")
    wait.add_argument("--owner")
    wait.add_argument("--kernel")
    wait.add_argument("--timeout", type=int)
    wait.add_argument("--interval", type=int)
    wait.set_defaults(func=cmd_wait)

    logs = sub.add_parser("logs", help="download the kernel log")
    logs.add_argument("--owner")
    logs.add_argument("--kernel")
    logs.set_defaults(func=cmd_logs)

    fetch = sub.add_parser("fetch", help="download the kernel output")
    fetch.add_argument("--owner")
    fetch.add_argument("--kernel")
    fetch.set_defaults(func=cmd_fetch)

    run = sub.add_parser("run", help="doctor -> build -> train -> wait -> fetch")
    run.add_argument("--execute", action="store_true", help="allow remote side effects")
    run.add_argument("--offline", action="store_true", help="skip network checks in doctor")
    run.add_argument("--owner")
    run.add_argument("--kernel")
    run.add_argument("--epochs", type=int)
    run.add_argument("--dim", type=int)
    run.add_argument("--timeout", type=int, help="kernel time cap in seconds")
    run.add_argument("--wait-timeout", type=int, default=7200)
    run.add_argument("--interval", type=int, default=60)
    run.add_argument("--push-dataset", action="store_true", help="also upload a dataset version")
    run.set_defaults(func=cmd_run)
    return parser


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - single error surface for CI
        log_event("command_failed", "error", command=args.command, error=redact(str(exc)))
        print(f"ERROR: {redact(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
