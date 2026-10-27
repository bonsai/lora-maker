#!/usr/bin/env python3
"""
Seed unified assets.db from existing Hokusai and Shishi sources.

Reads:
  data/hokusai/data/images-resized-720/
  data/hokusai/data/hokusai_vlm_reviews.jsonl
  data/shishi/metadata/frame_manifest.json

Outputs:
  data/assets.db

Usage:
  python tools/dashboard_api/seed_db.py
"""
import json
import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = REPO_ROOT / "data" / "assets.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def seed_hokusai(conn):
    """Import Hokusai images + VLM reviews."""
    images_dir = REPO_ROOT / "data" / "hokusai" / "data" / "images-resized-720"
    jsonl_path = REPO_ROOT / "data" / "hokusai" / "data" / "hokusai_vlm_reviews.jsonl"

    if not images_dir.exists():
        print("[seed] Hokusai images dir not found, skipping")
        return

    cur = conn.cursor()

    # Build review lookup
    reviews = {}
    if jsonl_path.exists():
        for line in open(jsonl_path, "r", encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                reviews[rec["image"]] = rec
            except Exception as e:
                print(f"[warn] bad jsonl line: {e}")

    inserted_frames = 0
    inserted_reviews = 0

    for img_path in sorted(images_dir.iterdir()):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue

        rel = f"data/hokusai/data/images-resized-720/{img_path.name}"
        size = img_path.stat().st_size

        cur.execute("""
            INSERT INTO frames (project_id, filename, relative_path, file_size_bytes, has_caption)
            VALUES (1, ?, ?, ?, FALSE)
            ON CONFLICT(project_id, relative_path) DO UPDATE SET
                file_size_bytes=excluded.file_size_bytes
        """, (img_path.name, rel, size))
        cur.execute("SELECT id FROM frames WHERE project_id=1 AND relative_path=?", (rel,))
        row = cur.fetchone()
        frame_id = row[0] if row else None
        inserted_frames += 1

        # VLM review
        rev = reviews.get(img_path.name)
        if rev:
            try:
                resp = json.loads(rev["response"])
            except Exception:
                continue

            subject = resp.get("subject", "")
            category = resp.get("category", "")
            style_notes = resp.get("style_notes", "")
            training_suitability = resp.get("training_suitability")
            notes = resp.get("notes", "")

            cur.execute("""
                INSERT INTO vlm_reviews (frame_id, subject, category, style_notes, training_suitability, notes, raw_response)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(frame_id) DO UPDATE SET
                    subject=excluded.subject,
                    category=excluded.category,
                    style_notes=excluded.style_notes,
                    training_suitability=excluded.training_suitability,
                    notes=excluded.notes,
                    raw_response=excluded.raw_response
            """, (frame_id, subject, category, style_notes, training_suitability, notes, rev["response"]))
            cur.execute("SELECT id FROM vlm_reviews WHERE frame_id=?", (frame_id,))
            row = cur.fetchone()
            review_id = row[0] if row else None
            inserted_reviews += 1

            # Scores
            scores = resp.get("lora_quality", {})
            for axis, score in scores.items():
                try:
                    score = int(score)
                except (ValueError, TypeError):
                    continue
                cur.execute("""
                    INSERT INTO vlm_scores (review_id, axis, score)
                    VALUES (?, ?, ?)
                    ON CONFLICT(review_id, axis) DO UPDATE SET score=excluded.score
                """, (review_id, axis, score))

    conn.commit()
    print(f"[hokusai] frames={inserted_frames}, reviews={inserted_reviews}")


def seed_shishi(conn):
    """Import Shishi videos + frames from frame_manifest.json."""
    manifest_path = REPO_ROOT / "data" / "shishi" / "metadata" / "frame_manifest.json"

    if not manifest_path.exists():
        print("[seed] Shishi manifest not found, skipping")
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cur = conn.cursor()

    inserted_videos = 0
    inserted_frames = 0

    for v in manifest.get("videos", []):
        vid = v["video_id"]

        # Upsert video
        cur.execute("""
            INSERT INTO videos (project_id, video_id, title, source_url, local_video_path,
                                duration_seconds, permission_status, rights_basis, creator, approved_at, notes)
            VALUES (2, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                title=excluded.title,
                source_url=excluded.source_url,
                local_video_path=excluded.local_video_path,
                permission_status=excluded.permission_status,
                rights_basis=excluded.rights_basis,
                creator=excluded.creator,
                notes=excluded.notes
        """, (
            vid,
            v.get("title"),
            v.get("source_url"),
            v.get("local_video", {}).get("path"),
            v.get("duration_seconds"),
            v.get("permission_status", "unknown"),
            v.get("rights_basis"),
            v.get("creator_or_rights_holder"),
            None,  # approved_at
            (v.get("notes") or ""),
        ))
        inserted_videos += 1

        # Frames
        for e in v.get("frames", {}).get("entries", []):
            rel = e["path"]
            cap_text = None
            if e.get("has_caption") and e.get("caption_path"):
                cap_file = REPO_ROOT / "data" / "shishi" / e["caption_path"]
                try:
                    cap_text = cap_file.read_text(encoding="utf-8").strip()
                except Exception:
                    cap_text = None

            cur.execute("""
                INSERT INTO frames (project_id, video_id, filename, relative_path, caption_path, caption_text,
                                    index_num, has_caption)
                VALUES (2, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, relative_path) DO UPDATE SET
                    caption_path=excluded.caption_path,
                    caption_text=excluded.caption_text,
                    has_caption=excluded.has_caption,
                    index_num=excluded.index_num
            """, (
                vid, e["filename"], rel, e.get("caption_path"),
                cap_text, e.get("index"), e.get("has_caption", False)
            ))
            inserted_frames += 1

    conn.commit()
    print(f"[shishi] videos={inserted_videos}, frames={inserted_frames}")


def main():
    print(f"[seed] target DB: {DB_PATH}")
    conn = init_db()
    seed_hokusai(conn)
    seed_shishi(conn)

    # Stats
    cur = conn.cursor()
    cur.execute("SELECT project_label, total_frames, captioned_frames, reviewed_frames, avg_suitability FROM v_frame_summary")
    for row in cur.fetchall():
        print(f"[stats] {row[0]}: frames={row[1]}, captioned={row[2]}, reviewed={row[3]}, avg_suit={row[4]}")
    conn.close()
    print("[seed] done")


if __name__ == "__main__":
    main()
