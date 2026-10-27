#!/usr/bin/env python3
"""
Shishi VLM Reviewer — batch review Shishi frames using the hokusai-manga VLM skill.

Reads:
  data/shishi/images-shishi/ (144 frames + captions)

Writes:
  data/shishi/metadata/shishi_vlm_reviews.jsonl
  data/shishi/metadata/shishi_vlm_reviews.db
  Also upserts into unified assets.db (vlm_reviews + vlm_scores tables)

Usage:
  python tools/shishi_vlm_review.py \
    --images data/shishi/images-shishi \
    --provider lmstudio \
    --model tempura-qwen2.5-vl-3b \
    --sample 10

  # Full run (all 144 frames)
  python tools/shishi_vlm_review.py --images data/shishi/images-shishi
"""
import argparse
import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

# Import the VLM reviewer skill from hokusai-manga
REVIEWER_PATH = Path(__file__).resolve().parent.parent / "data" / "hokusai-manga" / "agents" / "skills" / "reviewer"
sys.path.insert(0, str(REVIEWER_PATH))

spec = importlib.util.spec_from_file_location("vlm_reviewer", REVIEWER_PATH / "vlm_reviewer.py")
vlm_reviewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vlm_reviewer)
create_reviewer = vlm_reviewer.create_reviewer
VLMFrame = vlm_reviewer.VLMFrame
VLMConfig = vlm_reviewer.VLMConfig
VLMProvider = vlm_reviewer.VLMProvider

REPO_ROOT = Path(__file__).resolve().parent.parent

# Shishi-specific prompts
SHISHI_PROMPTS = {
    "full": """Analyze this Yamazaki Shishi (ヤマザキシシ) animation frame for LoRA training dataset. Return JSON:
{
  "subject": "brief description of what is depicted (character, pose, background, style)",
  "category": "character_portrait|character_full_body|animation_scene|watercolor_texture|abstract_composition|text_title|credits",
  "style_notes": "watercolor linework quality, color palette, rotoscope traces, paper texture, animation frame indicators",
  "lora_quality": {
    "linework": 1-10,
    "contrast": 1-10,
    "composition": 1-10,
    "artifact_free": 1-10,
    "shishi_style": 1-10
  },
  "training_suitability": 1-10,
  "notes": "any issues for training (compression artifacts, blur, text overlays, duplicate frames, low style fidelity)"
}""",

    "style": """Focus on SHISHI STYLE FIDELITY only:
- Watercolor/ink linework: fluid, expressive, hand-drawn feel?
- Color palette: muted pastels, paper-white highlights, characteristic Shishi tones?
- Rotoscope traces: subtle motion blur, frame-to-frame consistency?
- Paper texture: visible grain, organic imperfections?
- Overall style score (1-10): how uniquely "Shishi" does this frame feel?""",

    "quality": """Focus on TECHNICAL QUALITY only:
- Linework clarity: sharp, clean, or compressed/blurred?
- Contrast: well-balanced or washed out?
- Artifacts: JPEG blocks, text overlays, YouTube UI elements, duplicate frames?
- Frame uniqueness: distinct from adjacent frames?
- Overall technical score (1-10)""",

    "quick": """Quick assessment (2-3 sentences):
- What is the main subject? (character, text, abstract, scene)
- Style fidelity: Shishi watercolor look?
- Major issues?
- Training suitability score 1-10."""
}


def init_local_db(db_path: Path):
    """Initialize local SQLite DB for Shishi reviews."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image TEXT UNIQUE,
            video_id TEXT,
            frame_index INTEGER,
            response TEXT,
            error TEXT,
            provider TEXT,
            model TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def load_done_local(jsonl_path: Path):
    done = set()
    if jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["image"])
            except:
                pass
    return done


def parse_response_json(response_text: str):
    """Try to parse JSON from VLM response."""
    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response_text[start:end])
    except Exception:
        pass
    return None


def upsert_unified_db(frame_id: int, response_json: dict, provider: str, model: str):
    """Upsert VLM review into unified assets.db."""
    unified_db = REPO_ROOT / "data" / "assets.db"
    if not unified_db.exists():
        return

    conn = sqlite3.connect(unified_db)
    cur = conn.cursor()

    cur.execute("SELECT id FROM vlm_reviews WHERE frame_id=?", (frame_id,))
    existing = cur.fetchone()

    def to_str(v):
        if isinstance(v, dict):
            return json.dumps(v, ensure_ascii=False)
        return str(v) if v is not None else ""
    
    def to_float(v):
        if isinstance(v, dict):
            v = v.get("score") or v.get("value")
        try:
            return float(v) if v is not None else None
        except (ValueError, TypeError):
            return None
    
    subject = to_str(response_json.get("subject"))
    category = to_str(response_json.get("category"))
    style_notes = to_str(response_json.get("style_notes"))
    training_suitability = to_float(response_json.get("training_suitability"))
    notes = to_str(response_json.get("notes"))

    if existing:
        review_id = existing[0]
        cur.execute("""
            UPDATE vlm_reviews SET
                subject=?, category=?, style_notes=?, training_suitability=?, notes=?, raw_response=?
            WHERE id=?
        """, (subject, category, style_notes, training_suitability, notes, json.dumps(response_json), review_id))
    else:
        cur.execute("""
            INSERT INTO vlm_reviews (frame_id, subject, category, style_notes, training_suitability, notes, raw_response)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (frame_id, subject, category, style_notes, training_suitability, notes, json.dumps(response_json)))
        review_id = cur.lastrowid

    scores = response_json.get("lora_quality", {})
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
    conn.close()


def get_frame_id_from_db(frame_rel_path: str):
    """Look up frame_id in unified assets.db by relative_path."""
    unified_db = REPO_ROOT / "data" / "assets.db"
    if not unified_db.exists():
        return None
    conn = sqlite3.connect(unified_db)
    cur = conn.cursor()
    cur.execute("SELECT id FROM frames WHERE relative_path=?", (frame_rel_path,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def main():
    parser = argparse.ArgumentParser(description="Shishi VLM Batch Reviewer")
    parser.add_argument("--images", type=Path, required=True, help="Path to images-shishi/")
    parser.add_argument("--output-jsonl", type=Path, default=None, help="Output JSONL path")
    parser.add_argument("--output-db", type=Path, default=None, help="Output SQLite DB path")
    parser.add_argument("--provider", default="lmstudio", choices=[p.value for p in VLMProvider])
    parser.add_argument("--model", default="tempura-qwen2.5-vl-3b")
    parser.add_argument("--api-base", default="http://localhost:1234/v1")
    parser.add_argument("--prompt", choices=list(SHISHI_PROMPTS.keys()), default="full")
    parser.add_argument("--sample", type=int, default=0, help="Limit frames (0=all)")
    parser.add_argument("--skip-done", action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true", help="Validate setup without calling VLM")
    args = parser.parse_args()

    images_dir = args.images.resolve()
    if not images_dir.exists():
        print(f"Error: {images_dir} not found")
        sys.exit(1)

    jsonl_path = args.output_jsonl or (images_dir.parent / "metadata" / "shishi_vlm_reviews.jsonl")
    db_path = args.output_db or (images_dir.parent / "metadata" / "shishi_vlm_reviews.db")
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"=== Shishi VLM Batch Review ===")
    print(f"Images: {images_dir}")
    print(f"Output JSONL: {jsonl_path}")
    print(f"Output DB: {db_path}")
    print(f"Provider: {args.provider}")
    print(f"Model: {args.model}")
    print(f"Prompt: {args.prompt}")

    all_frames = sorted(images_dir.glob("*.png"))
    if args.sample > 0:
        all_frames = all_frames[:args.sample]

    print(f"Total frames: {len(all_frames)}")

    done = load_done_local(jsonl_path)
    remaining = [img for img in all_frames if img.name not in done]
    print(f"Already done: {len(done)}")
    print(f"Remaining: {len(remaining)}")

    if not remaining:
        print("All frames already processed!")
        return

    init_local_db(db_path)
    
    if args.dry_run:
        print("DRY RUN: Setup validated successfully.")
        print(f"Would process {len(remaining)} frames with {args.provider}/{args.model}")
        print(f"Prompt: {args.prompt}")
        return
    
    reviewer = create_reviewer(args.provider, args.model, api_base=args.api_base, max_image_size=720)
    prompt = SHISHI_PROMPTS[args.prompt]

    total_start = time.time()
    success = 0
    errors = 0

    for i, img in enumerate(remaining):
        parts = img.stem.split("_")
        video_id = "_".join(parts[:-1]) if len(parts) > 1 else "unknown"
        frame_index = int(parts[-1]) if parts[-1].isdigit() else 0

        frame = VLMFrame(path=img)
        result = reviewer.review_frame(frame, prompt)

        entry = {
            "image": img.name,
            "video_id": video_id,
            "frame_index": frame_index
        }
        if result.error:
            entry["error"] = result.error
            errors += 1
            print(f"  [{i+1}/{len(remaining)}] {img.name} - ERROR: {result.error}")
        else:
            entry["response"] = result.response
            success += 1
            print(f"  [{i+1}/{len(remaining)}] {img.name} - OK")

        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO reviews (image, video_id, frame_index, response, error, provider, model)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (img.name, video_id, frame_index, entry.get("response"), entry.get("error"), args.provider, args.model))
        conn.commit()
        conn.close()

        if not result.error:
            parsed = parse_response_json(result.response)
            if parsed:
                frame_rel = f"images-shishi/{img.name}"
                frame_id = get_frame_id_from_db(frame_rel)
                if frame_id:
                    upsert_unified_db(frame_id, parsed, args.provider, args.model)
                else:
                    print(f"    WARNING: Frame not in unified DB: {frame_rel}")

        if (i + 1) % 10 == 0:
            elapsed = time.time() - total_start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(remaining) - i - 1) / rate if rate > 0 else 0
            print(f"  Progress: {i+1}/{len(remaining)} | Success: {success} | Errors: {errors} | Rate: {rate:.2f}/s | ETA: {eta/60:.1f}min")

    total_elapsed = time.time() - total_start
    print(f"\n{'='*50}")
    print(f"BATCH COMPLETE")
    print(f"Total time: {total_elapsed/60:.1f} minutes")
    print(f"Success: {success}, Errors: {errors}")
    if total_elapsed > 0:
        print(f"Average rate: {len(remaining)/total_elapsed:.2f} images/sec")


if __name__ == "__main__":
    main()