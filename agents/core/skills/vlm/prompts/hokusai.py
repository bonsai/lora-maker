"""
Hokusai/MMX-specific VLM Prompts
For MMX spacecraft animation frame review.
"""

HOKUSAI_PROMPTS = {
    "full": """Analyze this MMX spacecraft animation frame. Provide detailed assessment:
1. Spacecraft visibility - fully visible? any clipping?
2. Color accuracy - can you see white thermal blankets, red/orange propulsion, dark blue solar panels, gray structure?
3. Lighting quality - three-point lighting (sun/fill/rim) working? starfield visible?
4. Camera framing - comfortable distance? rule of thirds? not too close/cluttered?
5. Geometry integrity - any vertex explosions, holes, collapsing meshes?
6. Composition - cinematic? clean? rule of thirds?
7. Overall score (1-10) with justification.""",
    
    "lighting": """Focus on LIGHTING only:
- Sun/key light: direction, intensity, shadows
- Fill light: shadow detail recovery
- Rim light: edge definition, separation from background
- World/background: starfield visibility, not overwhelming
- Overall exposure: over/under exposed?
Score lighting 1-10.""",
    
    "colors": """Focus on COLOR ACCURACY only:
- White thermal blankets (return modules) - visible?
- Red/orange propulsion (tanks) - distinct?
- Dark blue solar panels (paddle) - visible?
- Gray/titanium structure (PAF, legs) - distinct?
- Any color bleeding or washout?
Score color accuracy 1-10.""",
    
    "camera": """Focus on CAMERA FRAMING only:
- Distance: comfortable or claustrophobic?
- Lens: wide enough? distortion?
- Orbit: smooth? dizzying?
- Composition: rule of thirds? centered?
- Clipping: any parts cut off?
Score camera 1-10.""",
    
    "geometry": """Focus on GEOMETRY INTEGRITY only:
- Vertex explosions or spikes?
- Holes or missing faces?
- Decimation artifacts?
- Clean silhouettes?
- Mesh collapsing during animation?
Score geometry 1-10.""",
    
    "quick": """Quick assessment (2-3 sentences):
- What do you see?
- Major issues?
- Score 1-10.""",
}