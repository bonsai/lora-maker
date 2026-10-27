#!/usr/bin/env python3
"""Generate static HTML with embedded Shishi VLM review data."""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
JSONL_PATH = REPO_ROOT / "data" / "shishi" / "metadata" / "shishi_vlm_reviews.jsonl"
TEMPLATE_PATH = REPO_ROOT / "tools" / "dashboard_api" / "static" / "shishi_static.html"
OUTPUT_PATH = REPO_ROOT / "tools" / "dashboard_api" / "static" / "shishi_review.html"


def repair_json(raw: str) -> str:
    """Fix common LLM JSON issues."""
    # Fix missing commas between fields
    raw = re.sub(r'"\s*\n\s*"', '",\n"', raw)
    raw = re.sub(r'(\d|}|true|false|null|\])\s*\n\s*("|})', r'\1,\n\2', raw)
    # Fix unquoted values in objects: "key": value, -> "key": "value",
    raw = re.sub(r':\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*([,\}])', r': "\1"\2', raw)
    # Fix "1-10" values to numbers (take first number)
    raw = re.sub(r':\s*"1-10"', ': 5', raw)
    raw = re.sub(r':\s*1-10\b', ': 5', raw)
    # Fix trailing commas before } or ]
    raw = re.sub(r',\s*([}\]])', r'\1', raw)
    # Fix missing closing braces
    open_braces = raw.count('{')
    close_braces = raw.count('}')
    if open_braces > close_braces:
        raw += '}' * (open_braces - close_braces)
    return raw


def extract_training_suitability_fallback(resp_text: str):
    """Extract training_suitability from raw text using regex."""
    # Look for "training_suitability": number
    m = re.search(r'"training_suitability"\s*:\s*([0-9.]+)', resp_text)
    if m:
        try:
            return float(m.group(1))
        except:
            pass
    return None


def parse_response(resp_text: str) -> dict:
    """Extract JSON from VLM response, with repair for common LLM JSON issues."""
    # First try fallback extraction for training_suitability
    fallback_suit = extract_training_suitability_fallback(resp_text)
    
    try:
        start = resp_text.find("{")
        end = resp_text.rfind("}") + 1
        if start >= 0 and end > start:
            raw = resp_text[start:end]
            raw = repair_json(raw)
            parsed = json.loads(raw)
            # Normalize style_notes if it's an object
            sn = parsed.get("style_notes")
            if isinstance(sn, dict):
                parsed["style_notes"] = json.dumps(sn, ensure_ascii=False)
            # Ensure training_suitability is a number
            ts = parsed.get("training_suitability")
            if isinstance(ts, dict):
                parsed["training_suitability"] = ts.get("score") or ts.get("value")
            # Use fallback if main parse failed to get it
            if parsed.get("training_suitability") is None and fallback_suit is not None:
                parsed["training_suitability"] = fallback_suit
            return parsed
    except Exception:
        # Return minimal dict with fallback
        if fallback_suit is not None:
            return {"training_suitability": fallback_suit}
    return {}


def main():
    if not JSONL_PATH.exists():
        print(f"JSONL not found: {JSONL_PATH}")
        return

    frames = []
    reviewed = 0
    suitabilities = []
    with open(JSONL_PATH, encoding="utf-8") as f:
        for i, line in enumerate(f):
            try:
                entry = json.loads(line)
            except:
                continue

            parsed = parse_response(entry.get("response", ""))

            frame = {
                "id": i + 1,
                "filename": entry["image"],
                "video_id": entry.get("video_id"),
                "frame_index": entry.get("frame_index"),
                "caption_text": (REPO_ROOT / "data" / "shishi" / "images-shishi" / entry["image"].replace(".png", ".txt")).read_text(encoding="utf-8").strip() if (REPO_ROOT / "data" / "shishi" / "images-shishi" / entry["image"].replace(".png", ".txt")).exists() else "",
                "training_suitability": parsed.get("training_suitability"),
                "category": parsed.get("category"),
                "subject": parsed.get("subject"),
                "style_notes": parsed.get("style_notes"),
                "vlm_notes": parsed.get("notes"),
                "lora_quality": parsed.get("lora_quality", {}),
            }
            frames.append(frame)
            if frame["training_suitability"] is not None:
                reviewed += 1
                try:
                    suitabilities.append(float(frame["training_suitability"]))
                except:
                    pass

    stats = {
        "total": len(frames),
        "reviewed": reviewed,
        "avg_suit": round(sum(suitabilities) / len(suitabilities), 1) if suitabilities else None,
        "min_suit": min(suitabilities) if suitabilities else None,
        "max_suit": max(suitabilities) if suitabilities else None,
    }

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.replace("__FRAMES_JSON__", json.dumps(frames, ensure_ascii=False)) \
                   .replace("__STATS_JSON__", json.dumps(stats, ensure_ascii=False))

    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Generated: {OUTPUT_PATH}")
    print(f"Frames: {len(frames)}, Reviewed: {reviewed}")


if __name__ == "__main__":
    main()