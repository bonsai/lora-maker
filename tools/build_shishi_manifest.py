#!/usr/bin/env python3
"""
Build Shishi frame manifest from existing assets.

Scans:
  - data/shishi/images-shishi/   -> frame images + captions
  - data/shishi/local-videos/    -> downloaded MP4s
  - data/shishi/selected-videos.yml -> approval metadata

Outputs:
  - data/shishi/metadata/frame_manifest.json

Usage:
  python tools/build_shishi_manifest.py \
    --images data/shishi/images-shishi \
    --videos data/shishi/local-videos \
    --approvals data/shishi/selected-videos.yml \
    --output data/shishi/metadata/frame_manifest.json
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


def find_frames(images_dir: Path) -> dict:
    """
    Scan images-shishi/ and group by video_id.
    Returns: {video_id: [{path, caption_path, index}, ...]}
    """
    pattern = re.compile(r'^([A-Za-z0-9_-]+)_(\d{6})\.png$')
    frames_by_video = {}

    if not images_dir.exists():
        raise FileNotFoundError(f"Images directory not found: {images_dir}")

    for p in sorted(images_dir.iterdir()):
        m = pattern.match(p.name)
        if not m:
            continue
        video_id, idx = m.group(1), m.group(2)
        caption_path = p.with_suffix('.txt')
        entry = {
            "filename": p.name,
            "path": f"images-shishi/{p.name}",
            "caption_path": f"images-shishi/{caption_path.name}" if caption_path.exists() else None,
            "index": int(idx),
            "has_caption": caption_path.exists(),
        }
        frames_by_video.setdefault(video_id, []).append(entry)

    # Sort by index within each video
    for vid in frames_by_video:
        frames_by_video[vid].sort(key=lambda e: e["index"])

    return frames_by_video


def find_local_videos(videos_dir: Path) -> dict:
    """
    Scan local-videos/ for MP4 files.
    Returns: {video_id: {path, exists, size_bytes}}
    """
    result = {}
    if not videos_dir.exists():
        return result

    for subdir in videos_dir.iterdir():
        if not subdir.is_dir():
            continue
        mp4_candidates = list(subdir.glob("*.mp4"))
        if mp4_candidates:
            mp4 = mp4_candidates[0]
            result[subdir.name] = {
                "path": f"local-videos/{subdir.name}/{mp4.name}",
                "exists": True,
                "size_bytes": mp4.stat().st_size,
            }

    return result


def load_approvals(yaml_path: Path) -> dict:
    """
    Load selected-videos.yml.
    Returns: {video_id: approval_record}
    """
    if not yaml_path.exists():
        return {}

    with open(yaml_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    result = {}
    for rec in data.get('videos', []):
        vid = rec.get('video_id')
        if vid:
            result[vid] = rec

    return result


def build_manifest(images_dir: Path, videos_dir: Path, approvals_path: Path) -> dict:
    frames_by_video = find_frames(images_dir)
    local_videos = find_local_videos(videos_dir)
    approvals = load_approvals(approvals_path)

    all_video_ids = set(frames_by_video.keys()) | set(local_videos.keys()) | set(approvals.keys())

    videos = []
    total_frames = 0
    total_captions = 0

    for vid in sorted(all_video_ids):
        framelist = frames_by_video.get(vid, [])
        video_meta = local_videos.get(vid, {"exists": False, "path": None, "size_bytes": None})
        approval = approvals.get(vid, {})

        frame_count = len(framelist)
        caption_count = sum(1 for f in framelist if f["has_caption"])
        total_frames += frame_count
        total_captions += caption_count

        videos.append({
            "video_id": vid,
            "title": approval.get("notes", "").split("(")[0].strip() if approval else None,
            "source_url": approval.get("source_url"),
            "permission_status": approval.get("permission_status", "unknown"),
            "rights_basis": approval.get("rights_basis"),
            "creator_or_rights_holder": approval.get("creator_or_rights_holder"),
            "local_video": video_meta,
            "frames": {
                "count": frame_count,
                "first": framelist[0]["filename"] if framelist else None,
                "last": framelist[-1]["filename"] if framelist else None,
                "caption_coverage": f"{caption_count}/{frame_count}" if framelist else "0/0",
                "entries": framelist if framelist else [],
            },
        })

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "build_shishi_manifest.py",
        "videos": videos,
        "summary": {
            "total_videos_with_frames": len([v for v in videos if v["frames"]["count"] > 0]),
            "total_videos_approved": len([v for v in videos if v.get("permission_status") == "approved"]),
            "total_videos_downloaded": len([v for v in videos if v["local_video"].get("exists")]),
            "total_frames": total_frames,
            "total_captions": total_captions,
            "caption_coverage": f"{total_captions}/{total_frames}" if total_frames else "0/0",
        },
    }

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Build Shishi frame manifest")
    parser.add_argument("--images", type=Path, required=True, help="Path to images-shishi/")
    parser.add_argument("--videos", type=Path, required=True, help="Path to local-videos/")
    parser.add_argument("--approvals", type=Path, required=True, help="Path to selected-videos.yml")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON path")
    parser.add_argument("--pretty", action="store_true", default=True, help="Pretty-print JSON")
    args = parser.parse_args()

    manifest = build_manifest(args.images, args.videos, args.approvals)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2 if args.pretty else None)

    print(f"[manifest] wrote {len(manifest['videos'])} videos, {manifest['summary']['total_frames']} frames -> {args.output}")
    print(f"[summary] approved={manifest['summary']['total_videos_approved']}, downloaded={manifest['summary']['total_videos_downloaded']}, captions={manifest['summary']['caption_coverage']}")


if __name__ == "__main__":
    main()
