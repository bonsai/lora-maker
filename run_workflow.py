#!/usr/bin/env python3
"""Local-first runner for bonsai/lora-maker workflow YAMLs.

Never downloads source media, connects to Kaggle, uploads data, or trains a model.
All media processing requires explicit --execute and human-authored approval records.

Approval records are validated for evidence, scope, and reviewer, not just a
boolean flag. A template file (``*.template.json``) is never treated as an
approval.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
EVENT_LOG = RUNS / "events.jsonl"

SCHEMA_VERSION = 1
REQUIRED_VIDEO_USES = ("acquisition", "frame_extraction", "dataset_creation")
PRIVATE_SCOPES = ("local_only", "private_dataset")
VAGUE_RIGHTS_BASES = {
    "",
    "unknown",
    "none",
    "presumed",
    "assumed",
    "publicly_visible",
    "public",
    "n/a",
    "tbd",
    "unclear",
}
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

WORKFLOW_PATHS = {
    "01": ROOT / "workflows/01-domain-decision.yml",
    "02": ROOT / "workflows/02-reference-video-selection.yml",
    "03": ROOT / "workflows/03-dataset-preparation.yml",
    "04": ROOT / "workflows/04-kaggle-integration.yml",
}

WORKFLOW_03_SAFETY = (
    "default_dry_run",
    "no_acquisition_before_approval",
    "no_automatic_kaggle_upload",
    "private_visibility_only",
    "no_training_in_this_workflow",
    "no_public_release_without_new_approval",
    "never_overwrite_without_confirmation",
)


# ---------------------------------------------------------------- file helpers


def rel(path: Path, root: Path = ROOT) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Missing required YAML: {rel(path)}")
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping: {rel(path)}")
    return value


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_digest(rows: list[dict]) -> str:
    """Deterministic digest over image/caption hashes so approved content can be re-checked."""
    lines = []
    for row in sorted(rows, key=lambda item: str(item.get("image_path", ""))):
        lines.append(
            "|".join(
                str(row.get(field, ""))
                for field in ("image_path", "image_sha256", "caption_path", "caption_sha256")
            )
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def dataset_integrity_problems(root: Path, rows: list[dict], manifest: dict) -> list[str]:
    """Detect images/captions edited after the manifest was written or approved."""
    problems: list[str] = []
    for row in rows:
        for path_key, hash_key in (("image_path", "image_sha256"), ("caption_path", "caption_sha256")):
            path = root / str(row.get(path_key, ""))
            if not path.is_file():
                problems.append(f"missing {path_key}: {rel(path, root)}")
                continue
            digest = str(row.get(hash_key) or "")
            if not SHA256_PATTERN.match(digest):
                problems.append(f"{hash_key} is missing for {rel(path, root)}")
            elif sha256_file(path) != digest:
                problems.append(f"{path_key} changed after extraction: {rel(path, root)}")
    if content_digest(rows) != manifest.get("content_sha256"):
        problems.append("dataset content digest does not match manifest content_sha256")
    return problems


def existing_dataset_outputs(root: Path, config: dict) -> list[Path]:
    dataset_root = root / config["dataset"]["output_dir"]
    targets = [
        dataset_root / "README.md",
        dataset_root / Path(config["dataset"]["manifest"]["path"]).name,
        root / config["dataset"]["review"]["contact_sheet_path"],
    ]
    images = dataset_root / "images"
    if images.is_dir():
        targets.extend(
            sorted(path for path in images.iterdir() if path.is_file() and path.suffix.lower() in {".png", ".txt"})
        )
    return [path for path in targets if path.is_file()]


def stale_dataset_files(root: Path, config: dict, rows: list[dict]) -> list[Path]:
    """Image/caption files present on disk but absent from manifest.json."""
    images = root / config["dataset"]["output_dir"] / "images"
    if not images.is_dir():
        return []
    expected = set()
    for row in rows:
        for key in ("image_path", "caption_path"):
            if filled(row.get(key)):
                expected.add(Path(str(row[key])).name)
    return sorted(
        path
        for path in images.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".txt"} and path.name not in expected
    )


def clear_dataset_images(root: Path, config: dict) -> list[Path]:
    """Remove previous images/captions only after --overwrite was confirmed."""
    images = root / config["dataset"]["output_dir"] / "images"
    removed: list[Path] = []
    if not images.is_dir():
        return removed
    for path in sorted(images.iterdir()):
        if path.is_file() and path.suffix.lower() in {".png", ".txt"}:
            path.unlink()
            removed.append(path)
    return removed


def log_event(name: str, status: str, **details) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    row = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": name, "status": status, **details}
    with EVENT_LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def filled(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def valid_date(value) -> bool:
    if isinstance(value, datetime.datetime):
        return False
    if isinstance(value, datetime.date):
        # YAML turns an unquoted 2026-10-01 into a date object.
        return True
    if not isinstance(value, str) or not DATE_PATTERN.match(value.strip()):
        return False
    try:
        datetime.date.fromisoformat(value.strip())
    except ValueError:
        return False
    return True


# ------------------------------------------------------------ approval checks


def load_json_record(path: Path, purpose: str, root: Path = ROOT) -> tuple[dict | None, list[str]]:
    if not path.is_file():
        template = path.parent / f"{path.stem}.template.json"
        detail = f"approval missing: {rel(path, root)} ({purpose})"
        if template.is_file():
            detail += f"; {rel(template, root)} is a template, not an approval"
        return None, [detail]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"approval unreadable: {rel(path, root)} ({purpose}); invalid JSON at line {exc.lineno}"]
    if not isinstance(value, dict):
        return None, [f"approval unreadable: {rel(path, root)} ({purpose}); expected a JSON object"]
    return value, []


def validate_review_fields(record: dict, kind: str) -> list[str]:
    problems: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION}")
    if record.get("kind") != kind:
        problems.append(f"kind must be {kind!r}")
    if not filled(record.get("reviewed_by")):
        problems.append("reviewed_by must name the human who reviewed this")
    if not valid_date(record.get("reviewed_at")):
        problems.append("reviewed_at must be an ISO date (YYYY-MM-DD)")
    return problems


def validate_evidence(items, label: str = "permission_evidence") -> list[str]:
    if not isinstance(items, list) or not items:
        return [f"{label} must list at least one reviewed evidence entry"]
    problems: list[str] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            problems.append(f"{label} entry {index} must be a mapping")
            continue
        if not filled(item.get("reference")):
            problems.append(f"{label} entry {index} needs a reference (URL, file, or message id)")
        if not valid_date(item.get("checked_at")):
            problems.append(f"{label} entry {index} needs checked_at as YYYY-MM-DD")
        covers = item.get("covers")
        if not isinstance(covers, list) or not any(filled(use) for use in covers):
            problems.append(f"{label} entry {index} must name the uses it covers")
    return problems


def validate_domain_decision(record: dict) -> list[str]:
    problems = validate_review_fields(record, "domain_decision")
    if record.get("approved") is not True:
        problems.append("approved is not true")
    if not filled(record.get("subject_name")):
        problems.append("subject_name is required")
    if not filled(record.get("subject_type")):
        problems.append("subject_type is required")
    holder = str(record.get("rights_holder") or "").strip()
    if holder.lower() in VAGUE_RIGHTS_BASES:
        problems.append("rights_holder must name a holder or state that no holder exists")
    if record.get("intended_use") != "private_experiment":
        problems.append("intended_use must be private_experiment for this workflow")
    scope = record.get("publication_scope")
    if scope not in PRIVATE_SCOPES:
        problems.append(
            "publication_scope must be one of "
            f"{', '.join(PRIVATE_SCOPES)}; public release needs a separate approval"
        )
    urls = record.get("source_urls")
    if not isinstance(urls, list) or not any(filled(url) for url in urls):
        problems.append("source_urls must list at least one reviewed source")
    problems.extend(validate_evidence(record.get("permission_evidence")))
    return problems


def validate_selection_record(record: dict) -> list[str]:
    problems = validate_review_fields(record, "video_selection")
    if record.get("approved") is not True:
        problems.append("approved is not true")
    ids = record.get("selected_video_ids")
    clean_ids = [str(value).strip() for value in ids if filled(value)] if isinstance(ids, list) else []
    if not clean_ids:
        problems.append("selected_video_ids must list the approved videos")
    elif len(clean_ids) != len(set(clean_ids)):
        problems.append("selected_video_ids contains duplicates")
    uses = record.get("approved_uses")
    missing = [use for use in REQUIRED_VIDEO_USES if not (isinstance(uses, list) and use in uses)]
    if missing:
        problems.append(f"approved_uses must include: {', '.join(missing)}")
    if not isinstance(record.get("excluded_time_ranges"), list):
        problems.append("excluded_time_ranges must be an explicit list (an empty list is allowed)")
    reasons = record.get("reason_each_video_is_representative")
    if not isinstance(reasons, dict) or not reasons:
        problems.append("reason_each_video_is_representative must map each selected id to a reason")
    elif clean_ids:
        extra = sorted(set(reasons) - set(clean_ids))
        if extra:
            problems.append(
                "reason_each_video_is_representative includes ids not in selected_video_ids: "
                + ", ".join(extra)
            )
    return problems


def validate_videos(videos: list, approved_ids: set[str] | None = None) -> list[str]:
    problems: list[str] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, row in enumerate(videos, 1):
        if not isinstance(row, dict):
            problems.append(f"row {index} must be a mapping")
            continue
        missing = [field for field in ("video_id", "source_url", "local_path") if not filled(row.get(field))]
        if missing:
            problems.append(f"row {index} missing {', '.join(missing)}")
        video_id = str(row.get("video_id") or "").strip()
        url = str(row.get("source_url") or "").strip()
        if video_id and video_id in seen_ids:
            problems.append(f"row {index} duplicates video_id {video_id!r}")
        if url and url in seen_urls:
            problems.append(f"row {index} duplicates source_url")
        if row.get("permission_status") != "approved":
            problems.append(
                f"row {index} permission_status is {row.get('permission_status')!r}; only 'approved' can be processed"
            )
        basis = str(row.get("rights_basis") or "").strip()
        if basis.lower() in VAGUE_RIGHTS_BASES:
            problems.append(f"row {index} rights_basis must state the actual basis, not {basis or 'empty'!r}")
        if not filled(row.get("creator_or_rights_holder")):
            problems.append(f"row {index} creator_or_rights_holder is required")
        if not filled(row.get("terms_url")):
            problems.append(f"row {index} terms_url is required")
        uses = row.get("permitted_uses")
        missing_uses = [use for use in REQUIRED_VIDEO_USES if not (isinstance(uses, list) and use in uses)]
        if missing_uses:
            problems.append(f"row {index} permitted_uses missing: {', '.join(missing_uses)}")
        if not filled(row.get("reviewed_by")):
            problems.append(f"row {index} needs reviewed_by")
        if not valid_date(row.get("reviewed_at")):
            problems.append(f"row {index} needs reviewed_at as YYYY-MM-DD")
        if approved_ids is not None and video_id and video_id not in approved_ids:
            problems.append(f"row {index} video_id {video_id!r} is not covered by approval-record.json")
        seen_ids.add(video_id)
        seen_urls.add(url)
    return problems


def validate_dataset_approval(record: dict) -> list[str]:
    problems = validate_review_fields(record, "dataset_review")
    if record.get("approved") is not True:
        problems.append("approved is not true")
    for flag in ("captions_reviewed", "contact_sheet_reviewed"):
        if record.get(flag) is not True:
            problems.append(f"{flag} must be true")
    digest = record.get("manifest_sha256")
    if not (isinstance(digest, str) and SHA256_PATTERN.match(digest)):
        problems.append("manifest_sha256 must be the sha256 of the reviewed manifest.json")
    content = record.get("content_sha256")
    if not (isinstance(content, str) and SHA256_PATTERN.match(content)):
        problems.append("content_sha256 must be the dataset content digest shown by dataset --execute")
    return problems


def load_video_manifest(path: Path, root: Path = ROOT) -> tuple[list | None, list[str]]:
    if not path.is_file():
        return None, [f"selected video manifest missing: {rel(path, root)}"]
    try:
        doc = read_yaml(path)
    except (yaml.YAMLError, ValueError, FileNotFoundError) as exc:
        return None, [f"selected video manifest unreadable: {rel(path, root)} ({exc})"]
    videos = doc.get("videos", doc.get("selected_videos", []))
    if not isinstance(videos, list) or not videos:
        return None, [f"selected video manifest must contain a non-empty videos list: {rel(path, root)}"]
    return videos, []


def preflight(
    project_root: Path | None = None,
    manifest_rel: str = "selected-videos.yml",
    target_count: int | None = None,
) -> tuple[list[str], list[str]]:
    """Return (blockers, warnings). Read-only: never opens media or the network."""
    root = Path(project_root) if project_root else ROOT
    blockers: list[str] = []
    warnings: list[str] = []

    domain_path = root / "data/approvals/domain-decision.json"
    selection_path = root / "data/approvals/approval-record.json"
    manifest_path = root / manifest_rel

    domain, problems = load_json_record(domain_path, "domain/source", root)
    if domain is None:
        blockers.extend(problems)
    else:
        blockers.extend(f"{rel(domain_path, root)}: {item}" for item in validate_domain_decision(domain))

    selection, problems = load_json_record(selection_path, "video selection", root)
    approved_ids: set[str] | None = None
    if selection is None:
        blockers.extend(problems)
    else:
        blockers.extend(f"{rel(selection_path, root)}: {item}" for item in validate_selection_record(selection))
        ids = selection.get("selected_video_ids")
        if isinstance(ids, list):
            approved_ids = {str(value) for value in ids if filled(value)}
        reasons = selection.get("reason_each_video_is_representative")
        if isinstance(ids, list) and isinstance(reasons, dict):
            for video_id in sorted(approved_ids or set()):
                if video_id not in reasons:
                    blockers.append(
                        f"{rel(selection_path, root)}: no representativeness reason recorded for {video_id!r}"
                    )

    videos, problems = load_video_manifest(manifest_path, root)
    if videos is None:
        blockers.extend(problems)
    else:
        blockers.extend(f"{rel(manifest_path, root)}: {item}" for item in validate_videos(videos, approved_ids))
        manifest_ids = {
            str(row.get("video_id") or "").strip() for row in videos if isinstance(row, dict)
        }
        manifest_ids.discard("")
        if approved_ids:
            absent = sorted(approved_ids - manifest_ids)
            if absent:
                blockers.append(
                    f"{rel(selection_path, root)}: approved video ids missing from "
                    f"{rel(manifest_path, root)}: {', '.join(absent)}"
                )
        if target_count is not None and len(videos) != target_count:
            warnings.append(
                f"{rel(manifest_path, root)}: {len(videos)} videos selected; workflow target is {target_count} "
                "(count changes need explicit approval)"
            )
    return blockers, warnings


# --------------------------------------------------------------- workflow load


def execution_mode(config: dict) -> str | None:
    return config.get("execution", {}).get("mode") or config.get("workflow", {}).get("execution", {}).get("mode")


def load_workflows() -> dict[str, dict]:
    configs = {key: read_yaml(path) for key, path in WORKFLOW_PATHS.items()}
    for key, config in configs.items():
        if execution_mode(config) != "dry_run":
            raise ValueError(f"Workflow {key} must default to dry_run")
    safety = configs["03"].get("safety", {})
    missing = [flag for flag in WORKFLOW_03_SAFETY if safety.get(flag) is not True]
    if missing:
        raise ValueError(f"Workflow 03 is missing safety guarantees: {', '.join(missing)}")
    if configs["03"].get("kaggle", {}).get("visibility") != "private":
        raise ValueError("Workflow 03 must keep Kaggle visibility private")
    if configs["04"].get("human_approval", {}).get("default_visibility") != "private":
        raise ValueError("Workflow 04 must default to private visibility")
    return configs


def cmd_validate(_args) -> int:
    configs = load_workflows()
    print("Workflow YAML validation: OK")
    for key, config in configs.items():
        label = config.get("name") or config.get("workflow", {}).get("name") or config.get("id", "unnamed")
        print(f"  {key}: {label}")
    print("Safety defaults verified: dry-run; private visibility; no download, Kaggle upload, or training.")
    return 0


def cmd_preflight(args) -> int:
    config = load_workflows()["03"]
    manifest_rel = args.manifest or config["inputs"]["selected_manifest"]
    target = config["inputs"].get("target_video_count")
    blockers, warnings = preflight(ROOT, manifest_rel, target)
    print("PREFLIGHT: local and read-only; no video opened, no frame extracted, no upload.")
    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"  - {item}")
    if blockers:
        shown = blockers[: args.limit]
        print(f"Blocked pending human review ({len(blockers)} unresolved):")
        for item in shown:
            print(f"  - {item}")
        if len(blockers) > len(shown):
            print(f"  ... and {len(blockers) - len(shown)} more")
        print("Templates under data/approvals/ and selected-videos.example.yml are not approvals.")
        return 1
    print("Preflight passed. Add --execute only after reviewing evidence and approvals.")
    return 0


# ---------------------------------------------------------------- dataset work


def image_hash(frame) -> str:
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    mean = float(small.mean())
    bits = "".join("1" if float(pixel) >= mean else "0" for pixel in small.flatten())
    return f"{int(bits, 2):016x}"


def extract(args) -> int:
    configs = load_workflows()
    config = configs["03"]
    manifest_rel = config["inputs"]["selected_manifest"]
    manifest_path = ROOT / manifest_rel
    target = config["inputs"].get("target_video_count")

    blockers, warnings = preflight(ROOT, manifest_rel, target)
    if args.overwrite and not args.execute:
        raise ValueError("--overwrite requires --execute")
    existing = existing_dataset_outputs(ROOT, config)
    if not args.execute:
        print("DRY RUN: no local video opened, no frames extracted, no images written.")
        if warnings:
            print("Warnings:")
            for item in warnings:
                print(f"  - {item}")
        if existing:
            print(
                f"Note: {len(existing)} existing dataset output(s) would block --execute without --overwrite."
            )
            manifest_file = ROOT / config["dataset"]["output_dir"] / Path(config["dataset"]["manifest"]["path"]).name
            if manifest_file.is_file():
                try:
                    rows = json.loads(manifest_file.read_text(encoding="utf-8")).get("images", [])
                except (OSError, json.JSONDecodeError):
                    rows = []
                stale = stale_dataset_files(ROOT, config, rows) if rows else []
                if stale:
                    print(
                        f"Note: {len(stale)} file(s) in the images directory are not referenced by manifest.json."
                    )
                    print("--overwrite clears previous images/captions before regenerating.")
        if blockers:
            shown = blockers[: args.limit]
            print(f"Blocked pending human review ({len(blockers)} unresolved):")
            for item in shown:
                print(f"  - {item}")
            if len(blockers) > len(shown):
                print(f"  ... and {len(blockers) - len(shown)} more")
        else:
            print("Preflight passed. Add --execute only after reviewing evidence and approvals.")
        return 0

    if blockers:
        raise RuntimeError(
            "Refusing to execute; preflight is unresolved:\n  - " + "\n  - ".join(blockers[:20])
        )

    if existing and not args.overwrite:
        shown = ", ".join(rel(path) for path in existing[:5])
        raise RuntimeError(
            f"Refusing to overwrite {len(existing)} existing dataset output(s): {shown}"
            + (" ..." if len(existing) > 5 else "")
            + ". Review them, then re-run with --overwrite."
        )
    if existing:
        removed = clear_dataset_images(ROOT, config)
        log_event("dataset_overwrite_confirmed", "warning", count=len(existing), removed=len(removed))
        print(f"Removed {len(removed)} previous image/caption file(s) before regenerating.")

    import cv2

    videos, problems = load_video_manifest(manifest_path)
    if videos is None:
        raise RuntimeError(problems[0])
    interval = float(config["frames"]["extraction"]["interval_seconds"])
    threshold = int(config["frames"]["deduplication"]["max_hamming_distance"])
    max_frames = config["frames"]["extraction"].get("max_frames_per_video")
    output_dir = ROOT / config["dataset"]["output_dir"] / "images"
    seen: list[int] = []
    records: list[dict] = []
    planned = 0

    for video in videos:
        source = (ROOT / video["local_path"]).resolve()
        if not source.is_relative_to(ROOT.resolve()):
            raise ValueError(f"local_path must remain inside project: {video['local_path']}")
        if not source.is_file():
            raise FileNotFoundError(f"Local video not found: {rel(source)}")
        cap = cv2.VideoCapture(str(source))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open local video: {rel(source)}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        step = max(1, round(fps * interval)) if fps > 0 else 1
        frame_no = 0
        kept = 0
        while True:
            if max_frames is not None and kept >= int(max_frames):
                break
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
                    records.append(
                        {
                            "source_video_id": video["video_id"],
                            "source_url": video["source_url"],
                            "source_timestamp_seconds": round(timestamp, 3),
                            "image_path": f"{config['dataset']['output_dir']}/images/{filename}",
                            "caption_path": f"{config['dataset']['output_dir']}/images/{Path(filename).stem}.txt",
                            "image_width": width,
                            "image_height": height,
                            "perceptual_hash": digest,
                        }
                    )
                    seen.append(value)
                    kept += 1
                    output_dir.mkdir(parents=True, exist_ok=True)
                    if not cv2.imwrite(str(output_dir / filename), frame):
                        raise RuntimeError(f"Failed to write {filename}")
                planned += 1
            frame_no += 1
        cap.release()

    caption_template = config["captions"]["initial_template"]
    for record in records:
        image = ROOT / record["image_path"]
        caption = caption_template.format(trigger_token=config["captions"]["trigger_token"])
        caption_path = image.with_suffix(".txt")
        caption_path.write_text(caption + "\n", encoding="utf-8")
        record["image_sha256"] = sha256_file(image)
        record["caption_sha256"] = sha256_file(caption_path)
    dataset_root = ROOT / config["dataset"]["output_dir"]
    manifest = dataset_root / Path(config["dataset"]["manifest"]["path"]).name
    content = content_digest(records)
    write_json(
        manifest,
        {
            "project": config["project"]["name"],
            "intended_use": config["project"]["intended_use"],
            "publication_scope": config["project"]["publication_scope"],
            "visibility": config["package"]["intended_visibility"],
            "content_sha256": content,
            "images": records,
        },
    )
    readme = dataset_root / "README.md"
    readme.write_text(
        "# Private experiment dataset\n\nReview every image and caption manually. "
        "Source videos are not included. Confirm rights and terms independently.\n",
        encoding="utf-8",
    )
    make_contact_sheet(records, ROOT / config["dataset"]["review"]["contact_sheet_path"])
    digest = sha256_file(manifest)
    log_event("dataset_manifest_written", "success", path=rel(manifest), sha256=digest, content_sha256=content, images=len(records))
    print(f"Wrote {len(records)} images. Review captions and contact sheet before packaging.")
    print("Captions are placeholders, not verified descriptions.")
    print(f"manifest.json sha256: {digest}")
    print(f"dataset content sha256: {content}")
    print("After review, copy both hashes into data/approvals/dataset-approval.json")
    print("(manifest_sha256 and content_sha256).")
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
    config = load_workflows()["03"]
    approval_path = ROOT / "data/approvals/dataset-approval.json"
    record, problems = load_json_record(approval_path, "dataset review")
    if record is None:
        raise RuntimeError(problems[0])
    problems = validate_dataset_approval(record)
    if problems:
        raise RuntimeError("Dataset approval is incomplete:\n  - " + "\n  - ".join(problems))

    dataset_root = ROOT / config["dataset"]["output_dir"]
    images = dataset_root / "images"
    manifest = dataset_root / Path(config["dataset"]["manifest"]["path"]).name
    if not images.is_dir() or not manifest.is_file():
        raise FileNotFoundError("Dataset images or manifest missing; run dataset --execute first")
    if sha256_file(manifest) != record["manifest_sha256"]:
        raise RuntimeError("manifest.json changed after approval; re-review and update dataset-approval.json")

    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
    rows = manifest_doc.get("images", [])
    if not rows:
        raise RuntimeError("manifest.json contains no images")
    for row in rows:
        for key in ("image_path", "caption_path"):
            path = ROOT / row[key]
            if not path.is_file() or (key == "caption_path" and not path.read_text(encoding="utf-8").strip()):
                raise RuntimeError(f"Missing image/caption or empty caption: {rel(path)}")
    integrity = dataset_integrity_problems(ROOT, rows, manifest_doc)
    if integrity:
        raise RuntimeError(
            "Dataset content changed after extraction; re-run dataset --execute and re-approve:\n  - "
            + "\n  - ".join(integrity[:20])
        )
    if record["content_sha256"] != manifest_doc.get("content_sha256"):
        raise RuntimeError("dataset-approval.json content_sha256 does not match the reviewed dataset; re-approve")

    stale = stale_dataset_files(ROOT, config, rows)
    if stale:
        shown = ", ".join(rel(path) for path in stale[:5])
        raise RuntimeError(
            f"{len(stale)} file(s) in the images directory are not referenced by manifest.json: {shown}"
            + (" ..." if len(stale) > 5 else "")
            + ". Remove them or re-run dataset --execute --overwrite; packaging refuses a mixed directory."
        )

    output = ROOT / config["package"]["output_dir"] / config["package"]["filename"]
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite: {rel(output)}")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            for key in ("image_path", "caption_path"):
                path = ROOT / row[key]
                archive.write(path, Path("images") / path.name)
        archive.write(manifest, "manifest.json")
        archive.write(dataset_root / "README.md", "README.md")
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        if bad:
            output.unlink(missing_ok=True)
            raise RuntimeError(f"ZIP verification failed: {bad}")
    digest = sha256_file(output)
    log_event("dataset_zip_created", "success", path=rel(output), sha256=digest)
    write_json(
        RUNS / "summary.json",
        {"zip": rel(output), "sha256": digest, "visibility": "private"},
    )
    print(f"Created and verified {rel(output)} (sha256={digest})")
    return 0


def kaggle_plan(_args) -> int:
    config = load_workflows()["04"]
    archive = ROOT / "dist/yamazaki-shishi-sdxl-dataset.zip"
    if not archive.is_file():
        raise FileNotFoundError("Dataset ZIP missing; package and review it first")
    plan = {
        "dataset_slug": config["inputs"]["defaults"]["dataset_slug"],
        "visibility": "private",
        "archive": rel(archive),
        "sha256": sha256_file(archive),
        "adapter_preference": ["official_cli_or_api", "mcp", "crx_gui"],
        "dry_run": True,
        "upload_executed": False,
        "requires_human_approval": True,
    }
    write_json(ROOT / "kaggle-upload-plan.json", plan)
    print("Created local kaggle-upload-plan.json only; no network connection or upload.")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Local-first YAML workflow runner")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="Validate workflow YAML safety defaults").set_defaults(func=cmd_validate)

    check = sub.add_parser("preflight", help="Read-only report of unresolved approvals and manifest gaps")
    check.add_argument("--manifest", default=None, help="Path to selected-videos.yml (default from workflow 03)")
    check.add_argument("--limit", type=int, default=40, help="Maximum blockers to print")
    check.set_defaults(func=cmd_preflight)

    ds = sub.add_parser("dataset", help="Plan or locally extract frames from approved videos")
    ds.add_argument("--execute", action="store_true", help="Write local images; approval records required")
    ds.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing dataset outputs; requires --execute and explicit review first",
    )
    ds.add_argument("--limit", type=int, default=40, help="Maximum blockers to print in dry-run")
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
