# Shishi VLM Reviewer Skill

Vision-Language Model reviewer for Yamazaki Shishi (ヤマザキシシ) animation frames.

## Features

- **Multi-provider support**: LM Studio, OpenAI, Gemini, Ollama, Custom endpoints
- **Shishi-specific prompts**: Style fidelity, technical quality, quick assessment
- **Batch processing**: Incremental JSONL + SQLite output
- **Frame comparison**: Version-to-version comparison
- **Unified DB integration**: Auto-upserts to `data/assets.db` (vlm_reviews + vlm_scores)

## Installation

```bash
# No additional installation needed - part of lora-maker repo
# Requires: pi coding agent, kagglehub, diffusers, controlnet-aux
```

## Usage

### As Pi Skill

```bash
# Review frames with preset
pi skill run shishi_vlm_reviewer review data/shishi/images-shishi --prompt shishi_full

# Batch review all frames (incremental)
pi skill run shishi_vlm_reviewer batch data/shishi/images-shishi \
  --output-jsonl data/shishi/metadata/shishi_vlm_reviews.jsonl \
  --output-db data/shishi/metadata/shishi_vlm_reviews.db

# Quick review (sample 10 frames)
pi skill run shishi_vlm_reviewer review data/shishi/images-shishi --prompt shishi_quick --sample 10
```

### As CLI (standalone)

```bash
# Direct Python execution
python -m agents.skills.shishi_reviewer review data/shishi/images-shishi \
  --provider lmstudio --model tempura-qwen2.5-vl-3b --prompt shishi_full

# Batch review
python -m agents.skills.shishi_reviewer batch data/shishi/images-shishi \
  --output-jsonl data/shishi/metadata/shishi_vlm_reviews.jsonl

# Compare versions
python -m agents.skills.shishi_reviewer compare output/v1 output/v2
```

## Prompt Presets

| Preset | Focus | Output |
|--------|-------|--------|
| `shishi_full` | Complete review | Full JSON with subject, category, style_notes, lora_quality (5 axes), training_suitability, notes |
| `shishi_style` | Style fidelity | Watercolor linework, color palette, rotoscope traces, paper texture, style score |
| `shishi_quality` | Technical quality | Linework clarity, contrast, artifacts, frame uniqueness, quality score |
| `shishi_quick` | Quick assessment | 2-3 sentences + score 1-10 |

## Config Schema

```yaml
provider: lmstudio        # lmstudio, openai, gemini, ollama, custom
model: tempura-qwen2.5-vl-3b
api_base: http://localhost:1234/v1
api_key: ""               # For OpenAI/Gemini
max_tokens: 1000
temperature: 0.3
timeout: 120
```

## Output Format

### JSONL (per frame)

```json
{
  "image": "frame_001.png",
  "video_id": "gsQuyDa8Kgk",
  "frame_index": 0,
  "response": "{...parsed JSON...}",
  "provider": "lmstudio",
  "model": "tempura-qwen2.5-vl-3b"
}
```

### SQLite (local + unified DB)

- Local: `data/shishi/metadata/shishi_vlm_reviews.db`
- Unified: `data/assets.db` → `vlm_reviews` + `vlm_scores` tables

## Requirements

- LM Studio (or other VLM endpoint) running with vision model
- `kagglehub` for LoRA auto-download
- `diffusers`, `controlnet-aux`, `transformers`, `accelerate`
- Python 3.10+

## Integration with Pipeline

```python
# In your generation pipeline
from agents.skills.shishi_reviewer import ShishiVLMReviewerSkill

skill = ShishiVLMReviewerSkill({
    "provider": "lmstudio",
    "model": "tempura-qwen2.5-vl-3b"
})

# Review generated keyframes
result = skill.review_frames("output/keyframes", "shishi_full")
skill.save_results(result.data, "review_results.json")

# Or batch review all frames
skill.batch_review("output/keyframes", "reviews.jsonl", "reviews.db")
```