#!/usr/bin/env python3
"""
Shishi VLM Reviewer Skill for Pi Coding Agent
Provides: review_frames(), batch_review(), compare_versions()
Compatible with pi skill system.
"""
import os
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, asdict

# Add project root to path for imports
SKILL_DIR = Path(__file__).resolve().parent
REPO_ROOT = SKILL_DIR.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import the core reviewer from tools
from tools.shishi_vlm_review import (
    create_reviewer,
    VLMFrame,
    VLMConfig,
    VLMProvider,
    SHISHI_PROMPTS,
    parse_response_json,
    upsert_unified_db,
    get_frame_id_from_db,
    init_local_db,
    load_done_local,
)

@dataclass
class SkillResult:
    """Standardized skill result"""
    success: bool
    data: Any = None
    error: str = None
    metadata: Dict = None

class ShishiVLMReviewerSkill:
    """
    Shishi VLM Reviewer Skill
    
    Analyzes Yamazaki Shishi animation frames using Vision-Language Models.
    Supports multiple providers: LM Studio, OpenAI, Gemini, Ollama.
    
    Usage:
        skill = ShishiVLMReviewerSkill()
        results = skill.review_frames(frames_dir, "shishi_full")
        skill.save_results(results, "output.json")
    """
    
    name = "shishi_vlm_reviewer"
    description = "Vision-Language Model reviewer for Yamazaki Shishi animation frames"
    version = "1.0.0"
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.reviewer = None
        self._setup_reviewer()
    
    def _setup_reviewer(self):
        """Initialize VLM reviewer with config"""
        provider = self.config.get("provider", "lmstudio")
        model = self.config.get("model", "tempura-qwen2.5-vl-3b")
        api_base = self.config.get("api_base", "http://localhost:1234/v1")
        api_key = self.config.get("api_key", "")
        max_tokens = self.config.get("max_tokens", 1000)
        temperature = self.config.get("temperature", 0.3)
        timeout = self.config.get("timeout", 120)
        
        self.reviewer = create_reviewer(
            provider, model,
            api_base=api_base,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout
        )
    
    def review_frames(self, frames_dir: Union[str, Path], 
                      prompt_preset: str = "shishi_full",
                      custom_prompt: str = None,
                      sample: int = 0) -> SkillResult:
        """
        Review frames in directory with VLM.
        
        Args:
            frames_dir: Directory containing frame images
            prompt_preset: Preset name (shishi_full, shishi_style, shishi_quality, shishi_quick)
            custom_prompt: Custom prompt text (overrides preset)
            sample: Number of frames to sample (0 = all)
        
        Returns:
            SkillResult with review results
        """
        frames_dir = Path(frames_dir)
        if not frames_dir.exists():
            return SkillResult(False, error=f"Frames directory not found: {frames_dir}")
        
        # Load frames
        all_frames = sorted(frames_dir.glob("*.png"))
        if not all_frames:
            return SkillResult(False, error=f"No PNG frames found in {frames_dir}")
        
        if sample > 0 and sample < len(all_frames):
            step = len(all_frames) // sample
            all_frames = all_frames[::step][:sample]
        
        # Get prompt
        if custom_prompt:
            prompt = custom_prompt
        elif prompt_preset in SHISHI_PROMPTS:
            prompt = SHISHI_PROMPTS[prompt_preset]
        else:
            return SkillResult(False, error=f"Unknown preset: {prompt_preset}")
        
        # Review frames
        results = []
        for i, frame_path in enumerate(all_frames):
            frame = VLMFrame(path=frame_path, frame_num=i)
            result = self.reviewer.review_frame(frame, prompt)
            
            results.append({
                "frame": str(frame_path),
                "frame_num": i,
                "prompt": prompt,
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
            "prompt_preset": prompt_preset,
            "provider": self.config.get("provider"),
            "model": self.config.get("model"),
        })
    
    def batch_review(self, frames_dir: Union[str, Path],
                     output_jsonl: Union[str, Path],
                     output_db: Union[str, Path] = None,
                     prompt_preset: str = "shishi_full",
                     skip_done: bool = True) -> SkillResult:
        """
        Batch review all frames, saving incrementally to JSONL + SQLite.
        This wraps the tools.shishi_vlm_review.main logic.
        """
        # Delegate to the existing batch review implementation
        import subprocess
        cmd = [
            sys.executable, "-m", "tools.shishi_vlm_review",
            "--images", str(frames_dir),
            "--prompt", prompt_preset,
        ]
        if output_jsonl:
            cmd.extend(["--output-jsonl", str(output_jsonl)])
        if output_db:
            cmd.extend(["--output-db", str(output_db)])
        if skip_done:
            cmd.append("--skip-done")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
            if result.returncode == 0:
                return SkillResult(True, data={"output": result.stdout}, metadata={"cmd": cmd})
            else:
                return SkillResult(False, error=result.stderr, metadata={"cmd": cmd})
        except Exception as e:
            return SkillResult(False, error=str(e))
    
    def compare_versions(self, v1_dir: Union[str, Path], 
                         v2_dir: Union[str, Path],
                         criteria: List[str] = None) -> SkillResult:
        """Compare two version frame sets"""
        v1_dir = Path(v1_dir)
        v2_dir = Path(v2_dir)
        
        if not v1_dir.exists() or not v2_dir.exists():
            return SkillResult(False, error="One or both directories not found")
        
        v1_frames = sorted(v1_dir.glob("*.png"))
        v2_frames = sorted(v2_dir.glob("*.png"))
        
        if not v1_frames or not v2_frames:
            return SkillResult(False, error="No frames found in one or both directories")
        
        criteria = criteria or ["style_consistency", "quality", "artifact_free", "character_fidelity"]
        
        comparison_prompt = f"""Compare these two Yamazaki Shishi animation frames (Version 1 vs Version 2).
Evaluate on: {', '.join(criteria)}.
Provide scores (1-10) for each version and a verdict."""
        
        # Use first frame of each for comparison
        v1_frame = VLMFrame(path=v1_frames[0])
        v2_frame = VLMFrame(path=v2_frames[0])
        
        # This would need multi-image support - simplified for now
        return SkillResult(True, data={
            "v1_frame": str(v1_frame.path),
            "v2_frame": str(v2_frame.path),
            "criteria": criteria,
            "note": "Full comparison requires multi-image VLM support",
            "comparison_prompt": comparison_prompt,
        })
    
    def save_results(self, results: List[Dict], output_path: Union[str, Path]):
        """Save results to JSON"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Results saved to {output_path}")

# CLI for standalone use
def main():
    parser = argparse.ArgumentParser(description="Shishi VLM Reviewer Skill CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Common args
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--provider", default="lmstudio", 
                       choices=[p.value for p in VLMProvider])
    common.add_argument("--model", default="tempura-qwen2.5-vl-3b")
    common.add_argument("--api-base", default="http://localhost:1234/v1")
    common.add_argument("--max-tokens", type=int, default=1000)
    common.add_argument("--temperature", type=float, default=0.3)
    common.add_argument("--timeout", type=int, default=120)
    
    # review command
    review_parser = subparsers.add_parser("review", parents=[common],
        help="Review frames with VLM")
    review_parser.add_argument("frames_dir", help="Directory with frame PNGs")
    review_parser.add_argument("--prompt", choices=list(SHISHI_PROMPTS.keys()) + ["custom"], 
                              default="shishi_full")
    review_parser.add_argument("--custom-prompt", help="Custom prompt text")
    review_parser.add_argument("--sample", type=int, default=0, help="Number of frames to sample")
    review_parser.add_argument("--output", help="Output JSON file")
    
    # batch command
    batch_parser = subparsers.add_parser("batch", parents=[common],
        help="Batch review all frames (incremental)")
    batch_parser.add_argument("frames_dir", help="Directory with frame PNGs")
    batch_parser.add_argument("--prompt", choices=list(SHISHI_PROMPTS.keys()), default="shishi_full")
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
    
    # Build config
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
            prompt_preset=args.prompt,
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
    main()