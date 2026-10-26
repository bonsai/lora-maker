#!/usr/bin/env python3
"""Local-first runner for bonsai/lora-maker workflow YAMLs.

Never downloads source media, connects to Kaggle, uploads data, or trains a model.
All media processing requires explicit --execute and human-authored approval records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
EVENT_LOG = RUNS / "events.jsonl"


def read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Missing required YAML: {path.relative_to(ROOT)}")
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping: {path}")
    return value


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def log_event(name: str, status: str, **details) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    row = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": name, "status": status, **details}
    with EVENT_LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def approval(path: Path, purpose: str) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Missing {purpose} approval: {path.relative_to(ROOT)}")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("approved") is not True:
        raise RuntimeError(f"{purpose} approval must contain approved: true")
    return record


def load_workflows() -> dict[str, dict]:
    paths = {
        "01": ROOT / "workflows/01-domain-decision.yml",
        "02": ROOT / "workflows/02-reference-video-selection.yml",
        "03": ROOT / "workflows/03-dataset-preparation.yml",
        "04": ROOT / "workflows/04-kaggle-integration.yml",
    }
    configs = {key: read_yaml(path) for key, path in paths.items()}
    if configs["01"].get("execution", {}).get("mode") != "dry_run":
        raise ValueError("Workflow 01 must default to dry_run")
    if configs["03"].get("workflow", {}).get("execution", {}).get("mode") != "dry_run":
        raise ValueError("Workflow 03 must default to dry_run")
    if configs["04"].get("execution", {}).get("mode") != "dry_run":
        raise ValueError("Workflow 04 must default to dry_run")
    if configs["03"].get("safety", {}).get("no_automatic_kaggle_upload") is not True:
        raise ValueError("Workflow 03 must prohibit automatic Kaggle upload")
    return configs


def cmd_validate(_args) -> int:
    configs = load_workflows()
    print("Workflow YAML validation: OK")
    for key, cfg in configs.items():
        print(f"  {key}: {cfg.get('name') or cfg.get('workflow', {}).get('name') or cfg.get('id', 'unnamed')}")
    print("Safety defaults verified: dry-run; no download, Kaggle upload, or training.")
    return 0


def load_videos(path: Path) -> list[dict]:
    doc = read_yaml(path)
    videos = doc.get("videos", doc.get("selected_videos", []))
    if not isinstance(videos, list) or not videos:
        raise ValueError("selected-videos.yml must contain a non-empty videos list")
    ids, urls = set(), set()
    for index, row in enumerate(videos, 1):
        if not isinstance(row, dict):
            raise ValueError(f"Video row {index} must be a mapping")
        for field in ("video_id", "source_url", "local_path", "permission_status"):
            if not row.get(field):
                raise ValueError(f"Video row {index} missing {field}")
        if row["video_id"] in ids or row["source_url"] in urls:
            raise ValueError(f"Duplicate video id or URL in row {index}")
        if row["permission_status"] != "approved":
            raise ValueError(f"Video {row['video_id']} has not been approved for use")
        ids.add(row["video_id"])
        urls.add(row["source_url"])
    return videos


def image_hash(frame) -> str:
    import cv2
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    mean = float(small.mean())
    bits = "".join("1" if float(pixel) >= mean else "0" for pixel in small.flatten())
    return f"{int(bits, 2):016x}"


def extract(args) -> int:
    import cv2
    cfgs = load_workflows()
    cfg = cfgs["03"]
    approval(ROOT / "data/approvals/domain-decision.json", "domain/source")
    approval(ROOT / "data/approvals/approval-record.json", "video selection")
    manifest_path = ROOT / cfg["inputs"]["selected_manifest"]
    videos = load_videos(manifest_path)
    interval = float(cfg["frames"]["extraction"]["interval_seconds"])
    threshold = int(cfg["frames"]["deduplication"]["max_hamming_distance"])
    output_dir = ROOT / cfg["dataset"]["output_dir"] / "images"
    seen: list[int] = []
    records: list[dict] = []
    planned = 0

    for video in videos:
        source = (ROOT / video["local_path"]).resolve()
        if not source.is_relative_to(ROOT.resolve()):
            raise ValueError(f"local_path must remain inside project: {video['local_path']}")
        if not source.is_file():
            raise FileNotFoundError(f"Local video not found: {source}")
        cap = cv2.VideoCapture(str(source))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open local video: {source}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        step = max(1, round(fps * interval)) if fps > 0 else 1
        frame_no = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_no % step == 0:
                digest = image_hash(frame)
                value = int(digest, 16)
                if not any((value ^ old).bit_count() <= threshold for old in seen):
                    timestamp = frame_no / fps if fps > 0 else 0.0
                    height, width = frame.shape[:2]
                    filename = f"{video['video_id']}_{len(records):06d}.png"
                    records.append({
                        "source_video_id": video["video_id"],
                        "source_url": video["source_url"],
                        "source_timestamp_seconds": round(timestamp, 3),
                        "image_path": f"data/dataset/images/{filename}",
                        "caption_path": f"data/dataset/images/{Path(filename).stem}.txt",
                        "image_width": width,
                        "image_height": height,
                        "perceptual_hash": digest,
                        "review_status": "pending",
                    })
                    seen.append(value)
                    if args.execute:
                        output_dir.mkdir(parents=True, exist_ok=True)
                        if not cv2.imwrite(str(output_dir / filename), frame):
                            raise RuntimeError(f"Failed to write {filename}")
                planned += 1
            frame_no += 1
        cap.release()

    if not args.execute:
        print(f"DRY RUN: {len(videos)} local videos, {len(records)} unique candidate frames.")
        print("No images written. Add --execute only after reviewing approvals.")
        write_json(RUNS / "dry-run-summary.json", {"mode": "dry_run", "videos": len(videos), "candidate_frames": len(records)})
        return 0

    for record in records:
        image = ROOT / record["image_path"]
        caption = cfg["captions"]["initial_template"].format(trigger_token=cfg["captions"]["trigger_token"])
        image.with_suffix(".txt").write_text(caption + "\n", encoding="utf-8")
    manifest = ROOT / cfg["dataset"]["manifest"]["path"]
    write_json(manifest, {"project": cfg["project"]["name"], "images": records})
    readme = ROOT / cfg["dataset"]["output_dir"] / "README.md"
    readme.write_text(
        "# Private experiment dataset\n\nReview every image and caption manually. "
        "Source videos are not included. Confirm rights and terms independently.\n",
        encoding="utf-8",
    )
    make_contact_sheet(records, ROOT / cfg["dataset"]["review"]["contact_sheet_path"])
    print(f"Wrote {len(records)} images. Review captions and contact sheet before packaging.")
    print("Captions are placeholders, not verified descriptions.")
    return 0


def make_contact_sheet(records: list[dict], target: Path) -> None:
    from PIL import Image, ImageDraw
    thumbs = []
    for row in records:
        path = ROOT / row["image_path"]
        if path.is_file():
            im = Image.open(path).convert("RGB")
            im.thumbnail((240, 160))
            thumbs.append((im.copy(), path.name))
    if not thumbs:
        raise RuntimeError("No images available for contact sheet")
    cell_w, cell_h, cols = 260, 195, 4
    sheet = Image.new("RGB", (cols * cell_w, ((len(thumbs) + cols - 1) // cols) * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (im, name) in enumerate(thumbs):
        x, y = (i % cols) * cell_w, (i // cols) * cell_h
        sheet.paste(im, (x + 8, y + 8))
        draw.text((x + 8, y + 172), name, fill="black")
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target)


def package(_args) -> int:
    cfg = load_workflows()["03"]
    approval(ROOT / "data/approvals/dataset-approval.json", "dataset review")
    dataset_root = ROOT / cfg["dataset"]["output_dir"]
    images = dataset_root / "images"
    manifest = dataset_root / cfg["dataset"]["manifest"]["path"].split("/")[-1]
    if not images.is_dir() or not manifest.is_file():
        raise FileNotFoundError("Dataset images or manifest missing; run dataset --execute first")
    rows = json.loads(manifest.read_text(encoding="utf-8")).get("images", [])
    for row in rows:
        for key in ("image_path", "caption_path"):
            p = ROOT / row[key]
            if not p.is_file() or (key == "caption_path" and not p.read_text(encoding="utf-8").strip()):
                raise RuntimeError(f"Missing image/caption or empty caption: {p}")
    output = ROOT / cfg["package"]["output_dir"] / cfg["package"]["filename"]
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite: {output}")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(images.iterdir()):
            if path.is_file() and path.suffix.lower() in {".png", ".txt"}:
                archive.write(path, Path("images") / path.name)
        archive.write(manifest, "manifest.json")
        archive.write(dataset_root / "README.md", "README.md")
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        if bad:
            output.unlink(missing_ok=True)
            raise RuntimeError(f"ZIP verification failed: {bad}")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    log_event("dataset_zip_created", "success", path=str(output.relative_to(ROOT)), sha256=digest)
    write_json(RUNS / "summary.json", {"zip": str(output.relative_to(ROOT)), "sha256": digest, "visibility": "private"})
    print(f"Created and verified {output.relative_to(ROOT)} (sha256={digest})")
    return 0


def kaggle_plan(_args) -> int:
    cfg = load_workflows()["04"]
    archive = ROOT / "dist/yamazaki-shishi-sdxl-dataset.zip"
    if not archive.is_file():
        raise FileNotFoundError("Dataset ZIP missing; package and review it first")
    plan = {
        "dataset_slug": cfg["inputs"]["defaults"]["dataset_slug"],
        "visibility": "private",
        "archive": str(archive.relative_to(ROOT)),
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "adapter_preference": ["official_cli_or_api", "mcp", "crx_gui"],
        "dry_run": True,
        "upload_executed": False,
        "requires_human_approval": True,
    }
    write_json(ROOT / "kaggle-upload-plan.json", plan)
    print("Created local kaggle-upload-plan.json only; no network connection or upload.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Local-first YAML workflow runner")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="Validate workflow YAML safety defaults").set_defaults(func=cmd_validate)
    ds = sub.add_parser("dataset", help="Plan or locally extract frames from approved videos")
    ds.add_argument("--execute", action="store_true", help="Write local images; approval records required")
    ds.set_defaults(func=extract)
    sub.add_parser("package", help="Package reviewed local dataset ZIP").set_defaults(func=package)
    sub.add_parser("kaggle-plan", help="Write local upload plan only").set_defaults(func=kaggle_plan)
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        log_event("command_failed", "error", command=args.command, error=str(exc))
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
