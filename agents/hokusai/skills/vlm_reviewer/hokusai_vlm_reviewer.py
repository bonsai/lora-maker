#!/usr/bin/env python3
"""
Hokusai/MMX VLM Reviewer Skill
Project-specific wrapper for MMX spacecraft animation frame review.
Uses core VLM reviewer with MMX-specific prompts and workflows.
"""
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

from agents.core.skills.vlm import VLMReviewerSkill, VLMConfig, VLMFrame, create_reviewer
from agents.core.skills.vlm.prompts.hokusai import HOKUSAI_PROMPTS
from agents.core.skills.base import SkillResult


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class HokusaiVLMReviewerSkill:
    """
    Hokusai/MMX VLM Reviewer Skill - Project-specific wrapper.
    
    Usage:
        skill = HokusaiVLMReviewerSkill(provider="lmstudio", model="tempura-qwen2.5-vl-3b")
        result = skill.review_frames("data/hokusai/images", preset="full")
    """
    
    name = "hokusai_vlm_reviewer"
    description = "VLM reviewer for MMX spacecraft / Hokusai manga frames"
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
        if preset in HOKUSAI_PROMPTS:
            return HOKUSAI_PROMPTS[preset]
        raise ValueError(f"Unknown preset: {preset}. Available: {list(HOKUSAI_PROMPTS.keys())}")
    
    def review_frames(self, frames_dir: Union[str, Path], 
                      preset: str = "full",
                      custom_prompt: str = None,
                      sample: int = 0) -> SkillResult:
        """
        Review frames in directory with VLM.
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
        
        criteria = criteria or ["lighting", "colors", "geometry", "camera", "composition"]
        
        comparison_prompt = f"""Compare these two MMX spacecraft animation frames (Version 1 vs Version 2).
Evaluate on: {', '.join(criteria)}.
Provide scores (1-10) for each version and a verdict."""
        
        return SkillResult(True, data={
            "v1_frame": str(v1_frames[0]),
            "v2_frame": str(v2_frames[0]),
            "criteria": criteria,
            "comparison_prompt": comparison_prompt,
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
    parser = argparse.ArgumentParser(description="Hokusai VLM Reviewer Skill CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--provider", default="lmstudio", 
                       choices=[p.value for p in ["lmstudio", "openai", "gemini", "ollama", "custom"]])
    common.add_argument("--model", default="tempura-qwen2.5-vl-3b")
    common.add_argument("--api-base", default="http://localhost:1234/v1")
    common.add_argument("--max-tokens", type=int, default=1000)
    common.add_argument("--temperature", type=float, default=0.3)
    common.add_argument("--timeout", type=int, default=120)
    
    review_parser = subparsers.add_parser("review", parents=[common],
        help="Review frames with VLM")
    review_parser.add_argument("frames_dir", help="Directory with frame PNGs")
    review_parser.add_argument("--prompt", choices=list(HOKUSAI_PROMPTS.keys()) + ["custom"], default="full")
    review_parser.add_argument("--custom-prompt", help="Custom prompt text")
    review_parser.add_argument("--sample", type=int, default=0, help="Number of frames to sample")
    review_parser.add_argument("--output", help="Output JSON file")
    
    compare_parser = subparsers.add_parser("compare", parents=[common],
        help="Compare two version frame sets")
    compare_parser.add_argument("v1_dir", help="Version 1 frames directory")
    compare_parser.add_argument("v2_dir", help="Version 2 frames directory")
    compare_parser.add_argument("--criteria", nargs="+", 
                               default=["lighting", "colors", "geometry", "camera", "composition"])
    
    args = parser.parse_args()
    
    config = {
        "provider": args.provider,
        "model": args.model,
        "api_base": args.api_base,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "timeout": args.timeout,
    }
    
    skill = HokusaiVLMReviewerSkill(config)
    
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
            import sys
            sys.exit(1)
    
    elif args.command == "compare":
        result = skill.compare_versions(args.v1_dir, args.v2_dir, args.criteria)
        if result.success:
            print(json.dumps(result.data, indent=2, ensure_ascii=False))
        else:
            print(f"Error: {result.error}")
            import sys
            sys.exit(1)


if __name__ == "__main__":
    import sys
    main()