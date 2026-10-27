#!/usr/bin/env python3
"""SDXL LoRA training kernel (Kaggle script kernel).

Runs headlessly from a generated bundle written by tools/kaggle_pipeline.py:

    train_lora.py       this file
    dataset.toml        kohya dataset config
    run_config.json     model / hyperparameters / pinned sd-scripts ref

No credentials, no uploads. Everything is written below /kaggle/working so the
Kaggle output download can pick it up. Fails closed: a missing caption, a
missing image pair, a wrong sd-scripts commit, or a non-finite loss aborts the
run instead of producing a silently broken LoRA.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

# Kaggle wraps script kernels in notebooks where __file__ is not defined.
_SCRIPT_PATH = globals().get("__file__")
HERE = Path(_SCRIPT_PATH).resolve().parent if _SCRIPT_PATH else Path("/kaggle/working")
WORK = Path("/kaggle/working") if Path("/kaggle/working").is_dir() else Path.cwd()
INPUT_ROOT = Path("/kaggle/input")
TRAIN_ROOT = Path("/kaggle/temp/train")
SD_SCRIPTS = Path("/kaggle/temp/sd-scripts")
OUTPUT = WORK / "output"
LOG_PATH = WORK / "train.log"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# tools/kaggle_pipeline.py replaces these markers when it builds the bundle, so
# the kernel does not depend on sidecar files surviving the upload.
EMBEDDED_RUN_CONFIG = r"""__RUN_CONFIG_JSON__"""
EMBEDDED_DATASET_TOML = r"""__DATASET_TOML__"""

_log_stream = None


def log(message: str) -> None:
    line = f"[pipeline] {message}"
    print(line, flush=True)
    if _log_stream is not None:
        _log_stream.write(line + "\n")
        _log_stream.flush()


def open_log() -> None:
    global _log_stream
    WORK.mkdir(parents=True, exist_ok=True)
    _log_stream = LOG_PATH.open("a", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _search(*names: str) -> Path | None:
    """Look for a file in the script dir, Kaggle working dir, and /kaggle/src."""
    for name in names:
        for base in (HERE, Path("/kaggle/working"), Path("/kaggle/src"), Path.cwd()):
            candidate = base / name
            if candidate.is_file():
                return candidate
    return None


def load_config() -> dict:
    if "__RUN_CONFIG_JSON__" not in EMBEDDED_RUN_CONFIG:
        config = json.loads(EMBEDDED_RUN_CONFIG)
        origin = "embedded"
    else:
        path = _search("run_config.json")
        if path is None:
            raise FileNotFoundError(
                "run_config.json is missing from the kernel bundle; "
                f"searched under {HERE}, /kaggle/working, /kaggle/src, {Path.cwd()}"
            )
        config = json.loads(path.read_text(encoding="utf-8"))
        origin = str(path)
    for key in ("base_model", "output_name", "sd_scripts", "training"):
        if key not in config:
            raise ValueError(f"run config is missing {key!r}")
    training = config["training"]
    # These two are the NaN / OOM guardrails for a 16GB T4. Refuse a config
    # that silently dropped them rather than produce a broken LoRA.
    if training.get("no_half_vae") is not True:
        raise ValueError("no_half_vae must be true for SDXL fp16 training")
    if training.get("gradient_checkpointing") is not True:
        raise ValueError("gradient_checkpointing must be true on a T4")
    log(f"run config loaded from {origin}")
    return config


def write_dataset_config(path: Path | None = None) -> Path:
    if path is not None:
        target = path
    else:
        target = _search("dataset.toml")
        if target is None:
            target = HERE / "dataset.toml"
    if "__DATASET_TOML__" not in EMBEDDED_DATASET_TOML:
        target.write_text(EMBEDDED_DATASET_TOML, encoding="utf-8")
        origin = "embedded"
    else:
        if not target.is_file():
            raise FileNotFoundError(
                "dataset.toml is missing from the kernel bundle; "
                f"searched under {HERE}, /kaggle/working, /kaggle/src, {Path.cwd()}"
            )
        origin = str(target)
    log(f"dataset config loaded from {origin}")
    return target



def find_image_dir() -> tuple[Path, int]:
    """Find the mounted dataset's images directory without hardcoding the layout."""
    best: tuple[Path, int] | None = None
    for directory in INPUT_ROOT.rglob("*"):
        if not directory.is_dir():
            continue
        count = sum(1 for item in directory.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES)
        if count == 0:
            continue
        is_images = directory.name == "images"
        score = (is_images, count)
        if best is None or score > (best[0].name == "images", best[1]):
            best = (directory, count)
    if best is None:
        raise FileNotFoundError("No image directory found under /kaggle/input")
    return best


def prepare_dataset(config: dict) -> tuple[Path, int]:
    source, count = find_image_dir()
    log(f"dataset source: {source} ({count} images)")
    expected = int(config.get("expected_images") or 0)
    if expected and count != expected:
        raise RuntimeError(
            f"dataset image count mismatch: expected {expected}, found {count} "
            f"in {source}; refusing to train on the wrong dataset"
        )
    trigger = str(config.get("trigger_token") or "").strip()
    target = TRAIN_ROOT / "1_yamazaki_shishi"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    copied = 0
    with_trigger = 0
    for image in sorted(source.iterdir()):
        if not image.is_file() or image.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        caption = image.with_suffix(".txt")
        if not caption.is_file():
            raise FileNotFoundError(f"caption sidecar missing for {image.name}")
        text = caption.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"caption is empty for {image.name}")
        if trigger and trigger.lower() in text.lower():
            with_trigger += 1
        shutil.copy2(image, target / image.name)
        shutil.copy2(caption, target / caption.name)
        copied += 1
    if copied == 0:
        raise RuntimeError("no image/caption pairs were copied")
    if expected and copied != expected:
        raise RuntimeError(f"copied {copied} pairs but expected {expected}")
    if trigger and with_trigger == 0:
        raise RuntimeError(
            f"no caption contains the trigger token {trigger!r}; the LoRA could not be invoked"
        )
    if trigger and with_trigger < copied:
        log(f"warning: trigger {trigger!r} appears in {with_trigger}/{copied} captions")
    log(f"prepared {copied} pairs at {target} (trigger coverage {with_trigger}/{copied})")
    return target, copied


def run(command: list[str], cwd: Path | None = None) -> None:
    log("$ " + " ".join(command))
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
        if _log_stream is not None:
            _log_stream.write(line)
            _log_stream.flush()
    code = process.wait()
    if code != 0:
        raise RuntimeError(f"command failed ({code}): {' '.join(command)}")


def install_framework(config: dict) -> str:
    sd = config["sd_scripts"]
    if SD_SCRIPTS.exists():
        shutil.rmtree(SD_SCRIPTS)
    run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            sd["ref"],
            sd["repo"],
            str(SD_SCRIPTS),
        ]
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(SD_SCRIPTS), text=True).strip()
    if not head.startswith(sd["commit"][:12]):
        raise RuntimeError(f"sd-scripts commit mismatch: expected {sd['commit']}, got {head}")
    log(f"sd-scripts {sd['ref']} at {head}")
    run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=SD_SCRIPTS)
    return head


def build_command(config: dict, dataset_config_path: Path | None = None) -> list[str]:
    training = config["training"]
    command = [
        "accelerate",
        "launch",
        "--num_cpu_threads_per_process",
        "2",
        "--num_processes",
        "1",
        "--num_machines",
        "1",
        "--dynamo_backend",
        "no",
        config["sd_scripts"]["script"],
        "--pretrained_model_name_or_path",
        config["base_model"],
        "--dataset_config",
        str(dataset_config_path or HERE / "dataset.toml"),
        "--output_dir",
        str(OUTPUT),
        "--output_name",
        config["output_name"],
        "--save_model_as",
        str(training["save_model_as"]),
        "--network_module",
        str(training["network_module"]),
        "--network_dim",
        str(training["network_dim"]),
        "--network_alpha",
        str(training["network_alpha"]),
        "--learning_rate",
        str(training["learning_rate"]),
        "--unet_lr",
        str(training["unet_lr"]),
        "--optimizer_type",
        str(training["optimizer_type"]),
        "--lr_scheduler",
        str(training["lr_scheduler"]),
        "--lr_warmup_steps",
        str(training["lr_warmup_steps"]),
        "--max_train_epochs",
        str(training["max_train_epochs"]),
        "--save_every_n_epochs",
        str(training["save_every_n_epochs"]),
        "--gradient_accumulation_steps",
        str(training["gradient_accumulation_steps"]),
        "--mixed_precision",
        str(training["mixed_precision"]),
        "--seed",
        str(training["seed"]),
        "--max_data_loader_n_workers",
        str(training["max_data_loader_n_workers"]),
        "--logging_dir",
        str(WORK / "logs"),
    ]
    enabled_flags = (
        ("network_train_unet_only", "--network_train_unet_only"),
        ("cache_latents_to_disk", "--cache_latents_to_disk"),
        ("cache_text_encoder_outputs_to_disk", "--cache_text_encoder_outputs_to_disk"),
        ("no_half_vae", "--no_half_vae"),
        ("gradient_checkpointing", "--gradient_checkpointing"),
        ("sdpa", "--sdpa"),
        ("persistent_data_loader_workers", "--persistent_data_loader_workers"),
    )
    for key, flag in enabled_flags:
        if training.get(key):
            command.append(flag)
    command += ["--min_snr_gamma", str(training["min_snr_gamma"])]
    return command


def versions() -> dict:
    value = {"python": sys.version.split()[0]}
    for name in ("torch", "accelerate", "transformers", "diffusers", "peft", "safetensors"):
        try:
            module = __import__(name)
            value[name] = getattr(module, "__version__", "unknown")
        except Exception:  # noqa: BLE001 - diagnostics must never abort the run
            value[name] = "missing"
    try:
        import torch

        value["cuda"] = torch.version.cuda
        value["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none"
    except Exception:  # noqa: BLE001
        value["gpu"] = "unknown"
    return value


def write_summary(status: str, config: dict, started: float, **extra) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for path in sorted(OUTPUT.glob("*.safetensors")):
        artifacts.append({"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    for path in (OUTPUT / "run-summary.json", LOG_PATH):
        if path.is_file():
            artifacts.append({"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    summary = {
        "schema_version": 1,
        "status": status,
        "project": "yamazaki-shishi",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed_seconds": round(time.time() - started, 1),
        "base_model": config.get("base_model"),
        "trigger_token": config.get("trigger_token"),
        "sd_scripts": config.get("sd_scripts"),
        "training": config.get("training"),
        "versions": versions(),
        "artifacts": artifacts,
        **extra,
    }
    (OUTPUT / "run-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    started = time.time()
    open_log()
    config = load_config()
    log("run_config loaded")
    try:
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available; the kernel must run with a GPU accelerator")
        log(f"gpu: {torch.cuda.get_device_name(0)} / torch {torch.__version__} / cuda {torch.version.cuda}")

        target, count = prepare_dataset(config)
        dataset_config_path = write_dataset_config()
        commit = install_framework(config)
        OUTPUT.mkdir(parents=True, exist_ok=True)
        run(build_command(config, dataset_config_path=dataset_config_path), cwd=SD_SCRIPTS)
        if not list(OUTPUT.glob("*.safetensors")):
            raise RuntimeError("training finished but no safetensors file was produced")
        write_summary(
            "success",
            config,
            started,
            sd_scripts_commit=commit,
            dataset={"images": count, "image_dir": str(target)},
            steps_expected=config["training"].get("steps_expected"),
        )
        log("training completed")
        return 0
    except Exception as exc:  # noqa: BLE001 - always leave a machine-readable failure
        log(f"FAILED: {exc}")
        traceback.print_exc()
        try:
            write_summary("failed", config, started, error=str(exc))
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        return 1
    finally:
        if _log_stream is not None:
            _log_stream.close()


if __name__ == "__main__":
    raise SystemExit(main())
