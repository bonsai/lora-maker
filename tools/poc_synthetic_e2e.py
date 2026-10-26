#!/usr/bin/env python3
"""Synthetic end-to-end check for the local runner.

Builds a throwaway sandbox in the system temp directory, copies the runner and
workflow policy into it, generates rights-free synthetic videos, and writes
sandbox-only approval fixtures so every gate can be exercised:

    preflight -> dataset dry-run -> dataset --execute -> overwrite guard
    -> package gate -> caption tamper detection -> stale-file gate
    -> dataset --execute --overwrite -> package -> ZIP inspection

The fixtures are NOT rights approvals and the sandbox is never the repository.
This script refuses to run if the sandbox would land inside the repository, and
it never writes to the repository's data/approvals, data/local-videos, or dist.

Requires opencv-python and Pillow (used by the runner too).

Usage:
    python tools/poc_synthetic_e2e.py [--keep]

--keep leaves the sandbox in place and prints its path for inspection.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VIDEO_IDS = [f"vid{i:02d}" for i in range(1, 8)]
REVIEW_DAY = "2026-10-26"
CHECK_NAMES: list[tuple[str, bool]] = []


def log(message: str = "") -> None:
    print(message, flush=True)


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECK_NAMES.append((name, ok))
    log(("PASS " if ok else "FAIL ") + name)
    if not ok and detail:
        for line in detail.strip().splitlines()[:8]:
            log("     " + line)


def make_sandbox() -> Path:
    sandbox = Path(tempfile.mkdtemp(prefix="lora-poc-")).resolve()
    if sandbox.is_relative_to(REPO):
        shutil.rmtree(sandbox, ignore_errors=True)
        raise RuntimeError("refusing to build the sandbox inside the repository")
    shutil.copy2(REPO / "run_workflow.py", sandbox / "run_workflow.py")
    shutil.copytree(REPO / "workflows", sandbox / "workflows")
    for relative in ("data/approvals", "data/local-videos"):
        (sandbox / relative).mkdir(parents=True, exist_ok=True)
    return sandbox


def run(sandbox: Path, *args: str) -> tuple[int, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, "run_workflow.py", *args],
        cwd=sandbox,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_videos(sandbox: Path) -> None:
    import cv2
    import numpy as np

    target = sandbox / "data/local-videos"
    width, height, fps, frames = 192, 128, 10, 30
    for index, video_id in enumerate(VIDEO_IDS, 1):
        path = target / f"{video_id}.mp4"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        if not writer.isOpened():
            raise RuntimeError(f"cv2.VideoWriter could not open {path}")
        for frame_no in range(frames):
            second = frame_no // fps
            image = np.full((height, width, 3), 25, np.uint8)
            if index == 1:
                cv2.circle(image, (25 + frame_no * 3, 64), 28, (40, 40, 230), -1)
            elif index == 2:
                for x in range(0, width, 16):
                    shade = 255 if (x // 16 + second) % 2 == 0 else 30
                    image[:, x:x + 16] = (shade, 90, 255 - shade)
            elif index == 3:
                for y in range(0, height, 16):
                    for x in range(0, width, 16):
                        if (x // 16 + y // 16 + second) % 2 == 0:
                            image[y:y + 16, x:x + 16] = (220, 200, 40)
            elif index == 4:
                cv2.line(image, (0, 10 + second * 25), (width, height - 10), (60, 230, 60), 9)
            elif index == 5:
                cv2.rectangle(image, (10 + second * 20, 20), (100 + second * 20, 110), (230, 60, 200), -1)
            elif index == 6:
                cv2.ellipse(image, (96, 64), (70 - second * 10, 50), second * 25, 0, 360, (30, 180, 230), -1)
            else:
                image[::8, :] = (200, 200, 200)
                image[:, ::8] = (200, 200, 200)
                cv2.rectangle(image, (second * 40, 30), (second * 40 + 50, 100), (20, 20, 20), -1)
            cv2.putText(image, f"{index}-{second}", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
            writer.write(image)
        writer.release()
    log(f"generated {len(VIDEO_IDS)} synthetic videos in {target}")


def make_fixtures(sandbox: Path) -> None:
    approvals = sandbox / "data/approvals"
    marker = "SANDBOX-ONLY synthetic fixture; not a real rights approval"
    write_json(
        approvals / "domain-decision.json",
        {
            "schema_version": 1,
            "kind": "domain_decision",
            "approved": True,
            "project": "yamazaki-shishi",
            "subject_name": "synthetic geometric POC shapes",
            "subject_type": "generated_test_fixture",
            "rights_holder": "none (locally generated, no third-party content)",
            "intended_use": "private_experiment",
            "publication_scope": "private_dataset",
            "source_urls": ["local://poc-synthetic-shapes"],
            "permission_evidence": [
                {
                    "reference": "generated by poc_synthetic_e2e.py in a temp sandbox; no third-party material",
                    "checked_at": REVIEW_DAY,
                    "covers": ["acquisition", "frame_extraction", "dataset_creation"],
                }
            ],
            "reviewed_by": "poc harness (synthetic)",
            "reviewed_at": REVIEW_DAY,
            "notes": marker,
        },
    )
    write_json(
        approvals / "approval-record.json",
        {
            "schema_version": 1,
            "kind": "video_selection",
            "approved": True,
            "project": "yamazaki-shishi",
            "selected_video_ids": VIDEO_IDS,
            "approved_uses": ["acquisition", "frame_extraction", "dataset_creation"],
            "excluded_time_ranges": [],
            "reason_each_video_is_representative": {
                video_id: f"synthetic pattern {video_id} for pipeline coverage" for video_id in VIDEO_IDS
            },
            "reviewed_by": "poc harness (synthetic)",
            "reviewed_at": REVIEW_DAY,
            "notes": marker,
        },
    )
    lines = ["videos:"]
    for video_id in VIDEO_IDS:
        lines.extend(
            [
                f"  - video_id: {video_id}",
                f"    source_url: local://poc-synthetic-shapes/{video_id}",
                f"    local_path: data/local-videos/{video_id}.mp4",
                "    permission_status: approved",
                "    rights_basis: locally generated synthetic video; no third-party rights",
                "    creator_or_rights_holder: poc harness",
                "    terms_url: local://poc-synthetic-shapes/terms",
                "    permitted_uses: [acquisition, frame_extraction, dataset_creation]",
                "    reviewed_by: poc harness (synthetic)",
                f"    reviewed_at: {REVIEW_DAY}",
            ]
        )
    (sandbox / "selected-videos.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_hashes(output: str) -> tuple[str | None, str | None]:
    manifest = re.search(r"manifest\.json sha256: ([0-9a-f]{64})", output)
    content = re.search(r"dataset content sha256: ([0-9a-f]{64})", output)
    return (manifest.group(1) if manifest else None, content.group(1) if content else None)


def exercise(sandbox: Path) -> int:
    dataset = sandbox / "data/dataset"
    zip_path = sandbox / "dist/yamazaki-shishi-sdxl-dataset.zip"
    approvals = sandbox / "data/approvals"

    log("== 1. preflight ==")
    code, out = run(sandbox, "preflight")
    check("preflight exits 0 with evidence", code == 0, out)
    check("preflight reports no unresolved blockers", "unresolved" not in out.lower(), out)

    log("\n== 2. dataset dry-run ==")
    code, out = run(sandbox, "dataset")
    check("dry-run exits 0", code == 0, out)
    check("dry-run opens no media", "DRY RUN" in out, out)
    check("dry-run writes no images", not (dataset / "images").exists(), out)

    log("\n== 3. dataset --execute ==")
    code, out = run(sandbox, "dataset", "--execute")
    check("execute exits 0", code == 0, out)
    manifest_sha, content_sha = parse_hashes(out)
    check("execute prints both hashes", bool(manifest_sha and content_sha), out)
    manifest_path = dataset / "manifest.json"
    check("manifest.json exists", manifest_path.is_file(), out)
    manifest_doc = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    rows = manifest_doc.get("images", [])
    check("manifest has images", bool(rows), out)
    check("every image has a caption", all((sandbox / row["caption_path"]).is_file() for row in rows), out)
    check("contact sheet exists", (sandbox / "data/review/contact-sheet.jpg").is_file(), out)
    check("source videos stay outside dataset", not list(dataset.rglob("*.mp4")), out)
    log(f"images={len(rows)} manifest_sha={(manifest_sha or '')[:12]} content_sha={(content_sha or '')[:12]}")

    log("\n== 4. overwrite guard ==")
    code, out = run(sandbox, "dataset", "--execute")
    check("second execute is refused", code != 0, out)
    check("refusal names --overwrite", "--overwrite" in out, out)
    code, out = run(sandbox, "dataset", "--overwrite")
    check("--overwrite without --execute is refused", code != 0, out)
    check("refusal mentions --execute", "--execute" in out, out)

    log("\n== 5. package gate ==")
    code, out = run(sandbox, "package")
    check("package without approval fails", code != 0, out)
    check("failure mentions approval", "approval" in out.lower(), out)

    log("\n== 6. package with matching hashes ==")
    write_json(
        approvals / "dataset-approval.json",
        {
            "schema_version": 1,
            "kind": "dataset_review",
            "approved": True,
            "project": "yamazaki-shishi",
            "captions_reviewed": True,
            "contact_sheet_reviewed": True,
            "manifest_sha256": manifest_sha,
            "content_sha256": content_sha,
            "reviewed_by": "poc harness (synthetic)",
            "reviewed_at": REVIEW_DAY,
            "notes": "SANDBOX-ONLY synthetic fixture; hashes copied from this sandbox run",
        },
    )
    code, out = run(sandbox, "package")
    check("package succeeds", code == 0, out)
    check("ZIP created", zip_path.is_file(), out)
    check("package prints ZIP sha256", bool(re.search(r"sha256=([0-9a-f]{64})", out)), out)

    log("\n== 7. post-approval tamper detection ==")
    caption = sandbox / rows[0]["caption_path"]
    original = caption.read_text(encoding="utf-8")
    caption.write_text(original.rstrip("\n") + " edited\n", encoding="utf-8")
    code, out = run(sandbox, "package")
    check("edited caption is refused", code != 0, out)
    check("refusal mentions extraction/content", ("changed after extraction" in out) or ("content digest" in out), out)
    caption.write_text(original, encoding="utf-8")

    log("\n== 8. stale file gate ==")
    stale = dataset / "images/stale_extra.png"
    stale.write_bytes(b"stale")
    code, out = run(sandbox, "package")
    check("unreferenced file is refused", code != 0, out)
    check("refusal names mixed directory", "not referenced by manifest" in out, out)

    log("\n== 9. dataset --execute --overwrite clears stale files ==")
    code, out = run(sandbox, "dataset", "--execute", "--overwrite")
    check("overwrite execute succeeds", code == 0, out)
    check("overwrite reports removals", "Removed" in out, out)
    check("stale file is gone", not stale.exists(), out)
    new_manifest_sha, new_content_sha = parse_hashes(out)
    check("overwrite reproduces identical content hash", new_content_sha == content_sha, out)

    log("\n== 10. repackage and inspect ZIP ==")
    zip_path.unlink(missing_ok=True)
    if new_manifest_sha and new_manifest_sha != manifest_sha:
        record = json.loads((approvals / "dataset-approval.json").read_text(encoding="utf-8"))
        record["manifest_sha256"] = new_manifest_sha
        write_json(approvals / "dataset-approval.json", record)
    code, out = run(sandbox, "package")
    check("repackage succeeds", code == 0, out)

    expected = {"manifest.json", "README.md"}
    for row in rows:
        expected.add("images/" + Path(row["image_path"]).name)
        expected.add("images/" + Path(row["caption_path"]).name)
    if zip_path.is_file():
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            bad = archive.testzip()
        check("ZIP contains exactly the manifest files", set(names) == expected, str(sorted(set(names) ^ expected)))
        check("ZIP has no source videos", not any(name.endswith(".mp4") for name in names), str(names[:5]))
        check("ZIP has no stale file", "images/stale_extra.png" not in names, str(names[:5]))
        check("ZIP passes CRC test", bad is None, str(bad))
        approved = json.loads((approvals / "dataset-approval.json").read_text(encoding="utf-8"))
        check("approval manifest hash matches current manifest", approved["manifest_sha256"] == new_manifest_sha)

    log("\n== 11. packaging refuses to overwrite an existing ZIP ==")
    code, out = run(sandbox, "package")
    check("second package is refused", code != 0, out)
    check("refusal is about the existing ZIP", ("Refusing to overwrite" in out) or ("exists" in out), out)

    passed = sum(1 for _, ok in CHECK_NAMES if ok)
    failed = len(CHECK_NAMES) - passed
    log(f"\n== summary: {passed} passed, {failed} failed, {len(CHECK_NAMES)} checks ==")
    for name, ok in CHECK_NAMES:
        if not ok:
            log("  FAILED: " + name)
    if rows:
        log(f"images={len(rows)} zip_entries={len(expected)}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the synthetic end-to-end POC in a temp sandbox.")
    parser.add_argument("--keep", action="store_true", help="keep the temp sandbox and print its path")
    args = parser.parse_args()

    sandbox = make_sandbox()
    log(f"sandbox: {sandbox}")
    try:
        make_videos(sandbox)
        make_fixtures(sandbox)
        code = exercise(sandbox)
    finally:
        if args.keep:
            log(f"kept sandbox: {sandbox}")
        else:
            shutil.rmtree(sandbox, ignore_errors=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
