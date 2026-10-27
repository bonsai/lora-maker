#!/usr/bin/env python3
"""Append approved local-video frames to data/shishi/images-shishi without overwriting.

Dry-run is the default. This script never downloads media, uses the network,
uploads to Kaggle, trains a model, or deletes existing files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_workflow  # noqa: E402

TARGET = ROOT / "data/shishi/images-shishi"
MANIFEST = TARGET / "additions-manifest.json"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def perceptual_hash(frame, cv2) -> int:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    mean = float(small.mean())
    bits = "".join("1" if float(pixel) >= mean else "0" for pixel in small.flatten())
    return int(bits, 2)


def existing_hashes(cv2) -> list[int]:
    hashes = []
    if not TARGET.is_dir():
        return hashes
    for path in sorted(TARGET.iterdir()):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            image = cv2.imread(str(path))
            if image is not None:
                hashes.append(perceptual_hash(image, cv2))
    return hashes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Append frames from approved local videos to the shishi image folder."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually write new PNG/caption files; without this flag only report the plan.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between sampled frames (default: 1.0).",
    )
    args = parser.parse_args()

    if args.interval <= 0:
        parser.error("--interval must be greater than zero")

    config = run_workflow.load_workflows()["03"]
    manifest_rel = config["inputs"]["selected_manifest"]
    blockers, warnings = run_workflow.preflight(
        ROOT, manifest_rel, config["inputs"].get("target_video_count")
    )
    if warnings:
        for warning in warnings:
            print(f"WARNING: {warning}")
    if blockers:
        print("BLOCKED: approval preflight has unresolved items:")
        for blocker in blockers:
            print(f"  - {blocker}")
        print("No source video was opened and no image was written.")
        return 1

    videos, problems = run_workflow.load_video_manifest(ROOT / manifest_rel, ROOT)
    if problems or videos is None:
        print("BLOCKED: " + "; ".join(problems))
        return 1

    # Resolve and validate every source before opening any media.
    sources = []
    for video in videos:
        source = (ROOT / video["local_path"]).resolve()
        if not source.is_relative_to(ROOT.resolve()):
            print(f"BLOCKED: local_path escapes repository: {video['local_path']}")
            return 1
        if not source.is_file():
            print(f"BLOCKED: local source file missing: {video['local_path']}")
            return 1
        sources.append((video, source))

    if not args.execute:
        print("DRY RUN — no video opened and no files written.")
        print(f"Approved source videos: {len(sources)}")
        print(f"Destination: {TARGET.relative_to(ROOT).as_posix()}")
        print(f"Sampling interval: {args.interval:g}s")
        print("Existing image/caption pairs will be preserved; duplicates will be skipped.")
        print("Run again with --execute only after reviewing the approvals.")
        return 0

    try:
        import cv2
    except ImportError:
        print("ERROR: OpenCV is required locally (install the project's media dependencies).")
        return 2

    TARGET.mkdir(parents=True, exist_ok=True)
    seen = existing_hashes(cv2)
    new_rows = []
    skipped_duplicates = 0
    write_count = 0
    caption_template = config["captions"]["initial_template"]
    trigger_token = config["captions"]["trigger_token"]

    for video, source in sources:
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            print(f"ERROR: cannot open local video: {source.relative_to(ROOT).as_posix()}")
            capture.release()
            return 2
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frame_step = max(1, round(fps * args.interval)) if fps > 0 else 1
        frame_index = 0
        source_kept = 0
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame_index % frame_step != 0:
                    frame_index += 1
                    continue

                value = perceptual_hash(frame, cv2)
                if any((value ^ old).bit_count() <= int(config["frames"]["deduplication"]["max_hamming_distance"]) for old in seen):
                    skipped_duplicates += 1
                    frame_index += 1
                    continue

                timestamp = frame_index / fps if fps > 0 else 0.0
                stamp = f"{int(round(timestamp * 1000)):09d}"
                stem = f"{video['video_id']}_{stamp}"
                image_path = TARGET / f"{stem}.png"
                caption_path = TARGET / f"{stem}.txt"
                # Never overwrite: if either target exists, skip this frame.
                if image_path.exists() or caption_path.exists():
                    frame_index += 1
                    continue
                height, width = frame.shape[:2]
                if not cv2.imwrite(str(image_path), frame):
                    raise RuntimeError(f"failed to write {image_path}")
                caption = caption_template.format(trigger_token=trigger_token).strip()
                caption_path.write_text(caption + "\n", encoding="utf-8")
                seen.append(value)
                new_rows.append({
                    "source_video_id": video["video_id"],
                    "source_url": video["source_url"],
                    "source_local_path": video["local_path"],
                    "source_timestamp_seconds": round(timestamp, 3),
                    "image_path": image_path.relative_to(ROOT).as_posix(),
                    "caption_path": caption_path.relative_to(ROOT).as_posix(),
                    "image_sha256": sha256_file(image_path),
                    "caption_sha256": sha256_file(caption_path),
                    "image_width": width,
                    "image_height": height,
                    "perceptual_hash": f"{value:016x}",
                    "caption_review_required": True,
                })
                source_kept += 1
                write_count += 1
                frame_index += 1
        finally:
            capture.release()
        print(f"{video['video_id']}: added {source_kept} frame(s)")

    # Merge the additions ledger only; existing images and captions are untouched.
    previous = []
    if MANIFEST.is_file():
        try:
            doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
            previous = doc.get("images", []) if isinstance(doc, dict) else []
            if not isinstance(previous, list):
                raise ValueError("images must be a list")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"ERROR: refusing to replace unreadable additions manifest: {exc}")
            return 2
    existing_paths = {row.get("image_path") for row in previous if isinstance(row, dict)}
    additions = [row for row in new_rows if row["image_path"] not in existing_paths]
    combined = previous + additions
    temporary = MANIFEST.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"schema_version": 1, "append_only": True, "images": combined}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(MANIFEST)

    print(f"Added images: {write_count}")
    print(f"Skipped near-duplicates: {skipped_duplicates}")
    print(f"Additions manifest: {MANIFEST.relative_to(ROOT).as_posix()}")
    print("Captions are placeholders. Review every image/caption and contact sheet locally.")
    print("No upload, training, or public release was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
