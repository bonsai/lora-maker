"""
Shishi-specific VLM Prompts
For Yamazaki Shishi animation frame review.
"""

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
- Training suitability score 1-10.""",
}