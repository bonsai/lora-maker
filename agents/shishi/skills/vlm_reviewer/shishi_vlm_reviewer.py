#!/usr/bin/env python3
"""
Shishi VLM Reviewer Skill
Project-specific wrapper for Yamazaki Shishi animation frame review.
Uses core VLM reviewer with Shishi-specific prompts and workflows.
"""
import json
import sqlite3
import time
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from dataclasses import asdict

from agents.core.skills.vlm import VLMReviewerSkill, VLMConfig, VLMFrame, VLMResult, create_reviewer
from agents.core.skills.vlm.prompts.shishi import SHISHI_PROMPTS
from agents.core.skills.base import SkillResult


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


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
    """Try to parse JSON from VLM response, with repair for common issues."""
    import re
    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            raw = response_text[start:end]
            # Fix missing commas
            raw = re.sub(r'"\s*\n\s*"', '",\n"', raw)
            raw = re.sub(r'(\d|}|true|false|null|\])\s*\n\s*("|})', r'\1,\n\2', raw)
            raw = re.sub(r':\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*([,\}])', r': "\1"\2', raw)
            raw = re.sub(r',\s*([}\]])', r'\1', raw)
            return json.loads(raw)
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


class ShishiVLMReviewerSkill:
    """
    Shishi VLM Reviewer Skill - Project-specific wrapper.
    
    Usage:
        skill = ShishiVLMReviewerSkill(provider="lmstudio", model="tempura-qwen2.5-vl-3b")
        result = skill.review_frames("data/shishi/images-shishi", preset="full")
        skill.batch_review("data/shishi/images-shishi", "data/shishi/metadata/reviews.jsonl")
    """
    
    name = "shishi_vlm_reviewer"
    description = "VLM reviewer for Yamazaki Shishi animation frames"
    version = "1.0.0"
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.reviewer = None
        self._setup_reviewer()
    
    def _setup_reviewer(self):
        """Initialize VLM reviewer with config."""
        self.reviewer = create_reviewer(
            self.config.get("provider", "lmstudio"),
            self.config.get("model", "tempura-qwen2.5-vl-3b"),
            api_base=self.config.get("api_base", "http://localhost:1234/v1"),
            api_key=self.config.get("api_key", ""),
            max_tokens=self.config.get("max_tokens", 1000),
            temperature=self.config.get("temperature", 0.3),
            timeout=self.config.get("timeout", 120),
            max_image_size=self.config.get("max_image_size", 720),
        )
    
    def get_prompt(self, preset: str = "full", custom: str = None) -> str:
        """Get prompt by preset name or custom text."""
        if custom:
            return custom
        if preset in SHISHI_PROMPTS:
            return SHISHI_PROMPTS[preset]
        raise ValueError(f"Unknown preset: {preset}. Available: {list(SHISHI_PROMPTS.keys())}")
    
    def review_frames(self, frames_dir: Union[str, Path], 
                      preset: str = "full",
                      custom_prompt: str = None,
                      sample: int = 0) -> SkillResult:
        """
        Review frames in directory with VLM.
        
        Args:
            frames_dir: Directory containing frame images
            preset: Prompt preset (full, style, quality, quick)
            custom_prompt: Custom prompt text (overrides preset)
            sample: Number of frames to sample (0 = all)
        """
        frames_dir = Path(frames_dir)
        if not frames_dir.exists():
            return SkillResult(False, error=f"Frames directory not found: {frames_dir}")
        
        all_frames = sorted(frames_dir.glob("*.png"))
        if not all_frames:
            return SkillResult(False, error=f"No PNG frames found in {frames_dir}")
        
        if sample > 0 and sample < len(all_frames):
            step = max(1, len(all_frames) // sample)
            all_frames = all_frames[::step][:sample]
        
        prompt = self.get_prompt(preset, custom_prompt)
        
        results = []
        for i, frame_path in enumerate(all_frames):
            frame = VLMFrame(path=frame_path, frame_num=i)
            result = self.reviewer.review_frame(frame, prompt)
            
            results.append({
                "frame": str(frame_path),
                "frame_num": i,
                "prompt": preset,
                "response": result.response,
                "error": result.error,
                "provider": result.provider,
                "model": result.model,
                "latency_ms": result.latency_ms,
            })
            
            if result.error:
                print(f"  Error on {frame_path.name}: {result.error}")
            else:
                print(f"  [{i+1}/{len(all_frames)}] {frame_path.name} - OK")
        
        return SkillResult(True, data=results, metadata={
            "total_frames": len(all_frames),
            "preset": preset,
            "provider": self.config.get("provider"),
            "model": self.config.get("model"),
        })
    
    def batch_review(self, frames_dir: Union[str, Path],
                     output_jsonl: Union[str, Path],
                     output_db: Union[str, Path] = None,
                     preset: str = "full",
                     skip_done: bool = True) -> SkillResult:
        """
        Batch review all frames, saving incrementally to JSONL + SQLite.
        """
        frames_dir = Path(frames_dir)
        jsonl_path = Path(output_jsonl)
        db_path = Path(output_db) if output_db else (frames_dir.parent / "metadata" / "shishi_vlm_reviews.db")
        
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        all_frames = sorted(frames_dir.glob("*.png"))
        done = load_done_local(jsonl_path) if skip_done else set()
        remaining = [img for img in all_frames if img.name not in done]
        
        print(f"=== Shishi VLM Batch Review ===")
        print(f"Images: {frames_dir}")
        print(f"Total frames: {len(all_frames)}")
        print(f"Already done: {len(done)}")
        print(f"Remaining: {len(remaining)}")
        
        if not remaining:
            return SkillResult(True, data={"message": "All frames already processed!"}, metadata={})
        
        init_local_db(db_path)
        
        prompt = self.get_prompt(preset)
        total_start = time.time()
        success = 0
        errors = 0
        
        for i, img in enumerate(remaining):
            parts = img.stem.split("_")
            video_id = "_".join(parts[:-1]) if len(parts) > 1 else "unknown"
            frame_index = int(parts[-1]) if parts[-1].isdigit() else 0
            
            frame = VLMFrame(path=img)
            result = self.reviewer.review_frame(frame, prompt)
            
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
            """, (img.name, video_id, frame_index, entry.get("response"), entry.get("error"), 
                  self.config.get("provider", "lmstudio"), self.config.get("model", "tempura-qwen2.5-vl-3b")))
            conn.commit()
            conn.close()
            
            if not result.error:
                parsed = parse_response_json(result.response)
                if parsed:
                    frame_rel = f"images-shishi/{img.name}"
                    frame_id = get_frame_id_from_db(frame_rel)
                    if frame_id:
                        upsert_unified_db(frame_id, parsed, self.config.get("provider", "lmstudio"), self.config.get("model", "tempura-qwen2.5-vl-3b"))
            
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
        
        return SkillResult(True, data={
            "success": success,
            "errors": errors,
            "total_time_sec": total_elapsed,
        }, metadata={"jsonl": str(jsonl_path), "db": str(db_path)})
    
    def compare_versions(self, v1_dir: Union[str, Path], 
                         v2_dir: Union[str, Path],
                         criteria: List[str] = None) -> SkillResult:
        """Compare two version frame sets."""
        v1_dir = Path(v1_dir)
        v2_dir = Path(v2_dir)
        
        if not v1_dir.exists() or not v2_dir.exists():
            return SkillResult(False, error="One or both directories not found")
        
        v1_frames = sorted(v1_dir.glob("*.png"))
        v2_frames = sorted(v2_dir.glob("*.png"))
        
        if not v1_frames or not v2_frames:
            return SkillResult(False, error="No frames found in one or both directories")
        
        criteria = criteria or ["style_consistency", "quality", "artifact_free", "character_fidelity"]
        
        return SkillResult(True, data={
            "v1_frame": str(v1_frames[0]),
            "v2_frame": str(v2_frames[0]),
            "criteria": criteria,
            "note": "Full comparison requires multi-image VLM support"
        })
    
    def save_results(self, results: List[Dict], output_path: Union[str, Path]):
        """Save results to JSON."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Results saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Shishi VLM Reviewer Skill CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--provider", default="lmstudio", 
                       choices=[p.value for p in ["lmstudio", "openai", "gemini", "ollama", "custom"]])
    common.add_argument("--model", default="tempura-qwen2.5-vl-3b")
    common.add_argument("--api-base", default="http://localhost:1234/v1")
    common.add_argument("--max-tokens", type=int, default=1000)
    common.add_argument("--temperature", type=float, default=0.3)
    common.add_argument("--timeout", type=int, default=120)
    
    # review command
    review_parser = subparsers.add_parser("review", parents=[common],
        help="Review frames with VLM")
    review_parser.add_argument("frames_dir", help="Directory with frame PNGs")
    review_parser.add_argument("--prompt", choices=list(SHISHI_PROMPTS.keys()) + ["custom"], default="full")
    review_parser.add_argument("--custom-prompt", help="Custom prompt text")
    review_parser.add_argument("--sample", type=int, default=0, help="Number of frames to sample")
    review_parser.add_argument("--output", help="Output JSON file")
    
    # batch command
    batch_parser = subparsers.add_parser("batch", parents=[common],
        help="Batch review all frames (incremental)")
    batch_parser.add_argument("frames_dir", help="Directory with frame PNGs")
    batch_parser.add_argument("--prompt", choices=list(SHISHI_PROMPTS.keys()), default="full")
    batch_parser.add_argument("--output-jsonl", help="Output JSONL file")
    batch_parser.add_argument("--output-db", help="Output SQLite DB file")
    batch_parser.add_argument("--no-skip-done", action="store_true")
    
    # compare command
    compare_parser = subparsers.add_parser("compare", parents=[common],
        help="Compare two version frame sets")
    compare_parser.add_argument("v1_dir", help="Version 1 frames directory")
    compare_parser.add_argument("v2_dir", help="Version 2 frames directory")
    compare_parser.add_argument("--criteria", nargs="+", 
                               default=["style_consistency", "quality", "artifact_free", "character_fidelity"])
    
    args = parser.parse_args()
    
    config = {
        "provider": args.provider,
        "model": args.model,
        "api_base": args.api_base,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "timeout": args.timeout,
    }
    
    skill = ShishiVLMReviewerSkill(config)
    
    if args.command == "review":
        result = skill.review_frames(
            args.frames_dir,
            preset=args.prompt,
            custom_prompt=args.custom_prompt,
            sample=args.sample
        )
        if result.success and args.output:
            skill.save_results(result.data, args.output)
        elif result.success:
            print(json.dumps(result.data, indent=2, ensure_ascii=False))
        else:
            print(f"Error: {result.error}")
            sys.exit(1)
    
    elif args.command == "batch":
        result = skill.batch_review(
            args.frames_dir,
            args.output_jsonl,
            args.output_db,
            args.prompt,
            not args.no_skip_done
        )
        if result.success:
            print("Batch review completed")
            print(result.data)
        else:
            print(f"Error: {result.error}")
            sys.exit(1)
    
    elif args.command == "compare":
        result = skill.compare_versions(args.v1_dir, args.v2_dir, args.criteria)
        if result.success:
            print(json.dumps(result.data, indent=2, ensure_ascii=False))
        else:
            print(f"Error: {result.error}")
            sys.exit(1)


if __name__ == "__main__":
    import sys
    main()