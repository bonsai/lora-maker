#!/usr/bin/env python3
"""
Core VLM Reviewer Skill
Shared Vision-Language Model reviewer for all projects.
Supports: LM Studio, OpenAI, Gemini, Ollama, Custom OpenAI-compatible endpoints.
"""
import os
import sys
import json
import base64
import requests
import io
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, asdict, field
from enum import Enum

from agents.core.skills.base import Skill, SkillConfig, SkillResult


class VLMProvider(Enum):
    LMSTUDIO = "lmstudio"
    OPENAI = "openai"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    CUSTOM = "custom"


@dataclass
class VLMConfig(SkillConfig):
    """Configuration for VLM reviewer."""
    provider: VLMProvider = VLMProvider.LMSTUDIO
    model: str = "tempura-qwen2.5-vl-3b"
    api_base: str = "http://localhost:1234/v1"
    api_key: Optional[str] = None
    max_tokens: int = 1000
    temperature: float = 0.3
    timeout: int = 120
    max_image_size: int = 720  # Resize images larger than this (max dimension)
    
    def __post_init__(self):
        if isinstance(self.provider, str):
            self.provider = VLMProvider(self.provider.lower())


@dataclass
class VLMFrame:
    """Frame to be reviewed."""
    path: Union[str, Path]
    frame_num: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VLMResult:
    """Result of VLM review."""
    frame: str
    frame_num: Optional[int]
    prompt: str
    response: str
    provider: str
    model: str
    tokens_used: Optional[int] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None


class VLMReviewerSkill(Skill):
    """
    Core VLM Reviewer Skill - Analyze images using Vision-Language Models.
    
    Usage:
        skill = VLMReviewerSkill(VLMConfig(provider="lmstudio", model="tempura-qwen2.5-vl-3b"))
        result = skill.review_frame("image.png", "Describe this image")
        results = skill.review_frames(["img1.png", "img2.png"], "Describe")
    """
    
    name = "vlm_reviewer"
    description = "Vision-Language Model reviewer for images"
    version = "1.0.0"
    
    def __init__(self, config: Optional[VLMConfig] = None):
        super().__init__(config or VLMConfig())
        self.session = requests.Session()
        self._setup_provider()
    
    def _setup_provider(self):
        """Configure API endpoints based on provider."""
        cfg = self.config
        if cfg.provider == VLMProvider.LMSTUDIO:
            self.chat_url = f"{cfg.api_base}/chat/completions"
            self.headers = {"Content-Type": "application/json"}
        elif cfg.provider == VLMProvider.OPENAI:
            self.chat_url = "https://api.openai.com/v1/chat/completions"
            self.headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg.api_key or os.getenv('OPENAI_API_KEY')}"
            }
        elif cfg.provider == VLMProvider.GEMINI:
            self.chat_url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.model}:generateContent"
            self.headers = {"Content-Type": "application/json"}
        elif cfg.provider == VLMProvider.OLLAMA:
            self.chat_url = f"{cfg.api_base}/api/chat"
            self.headers = {"Content-Type": "application/json"}
        else:  # CUSTOM
            self.chat_url = f"{cfg.api_base}/chat/completions"
            self.headers = {"Content-Type": "application/json"}
    
    def _encode_image(self, image_path: Union[str, Path]) -> str:
        """Encode image to base64, with optional resize."""
        image_path = Path(image_path)
        
        # Check if resize needed
        try:
            from PIL import Image
            HAS_PIL = True
        except ImportError:
            HAS_PIL = False
        
        if self.config.max_image_size and HAS_PIL:
            try:
                with Image.open(image_path) as im:
                    w, h = im.size
                    if max(w, h) > self.config.max_image_size:
                        if w > h:
                            new_w = self.config.max_image_size
                            new_h = int(h * self.config.max_image_size / w)
                        else:
                            new_h = self.config.max_image_size
                            new_w = int(w * self.config.max_image_size / h)
                        im = im.resize((new_w, new_h), Image.LANCZOS)
                        
                        buf = io.BytesIO()
                        im.save(buf, format='PNG', optimize=True)
                        return base64.b64encode(buf.getvalue()).decode('utf-8')
            except Exception as e:
                print(f"Warning: Failed to resize {image_path}: {e}")
        
        # Fallback: encode original
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    
    def _build_payload(self, prompt: str, b64_image: str) -> Dict:
        """Build provider-specific payload."""
        cfg = self.config
        if cfg.provider in (VLMProvider.LMSTUDIO, VLMProvider.OPENAI, VLMProvider.CUSTOM):
            model = cfg.model or ("gpt-4o" if cfg.provider == VLMProvider.OPENAI else cfg.model)
            return {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}}
                    ]
                }],
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature
            }
        elif cfg.provider == VLMProvider.GEMINI:
            return {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/png", "data": b64_image}}
                    ]
                }],
                "generationConfig": {"maxOutputTokens": cfg.max_tokens, "temperature": cfg.temperature}
            }
        elif cfg.provider == VLMProvider.OLLAMA:
            return {
                "model": cfg.model,
                "messages": [{
                    "role": "user",
                    "content": prompt,
                    "images": [b64_image]
                }],
                "options": {"temperature": cfg.temperature}
            }
        return {}
    
    def _parse_response(self, resp_json: Dict) -> str:
        """Extract text from provider-specific response."""
        cfg = self.config
        if cfg.provider in (VLMProvider.LMSTUDIO, VLMProvider.OPENAI, VLMProvider.OLLAMA, VLMProvider.CUSTOM):
            return resp_json.get('choices', [{}])[0].get('message', {}).get('content', '')
        elif cfg.provider == VLMProvider.GEMINI:
            return resp_json.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
        return str(resp_json)
    
    def execute(self, frame: Union[str, Path, VLMFrame], prompt: str) -> SkillResult:
        """Review a single frame with a prompt. Main entry point."""
        import time
        
        if isinstance(frame, VLMFrame):
            frame_path = frame.path
            frame_num = frame.frame_num
        else:
            frame_path = frame
            frame_num = None
        
        frame_path = Path(frame_path)
        if not frame_path.exists():
            return SkillResult(False, error=f"Frame not found: {frame_path}")
        
        b64 = self._encode_image(frame_path)
        payload = self._build_payload(prompt, b64)
        
        params = {}
        if self.config.provider == VLMProvider.GEMINI:
            params['key'] = self.config.api_key or os.getenv('GEMINI_API_KEY')
        
        start = time.time()
        try:
            resp = self.session.post(
                self.chat_url, json=payload, params=params,
                headers=self.headers, timeout=self.config.timeout
            )
            latency = int((time.time() - start) * 1000)
            
            if resp.status_code == 200:
                response_text = self._parse_response(resp.json())
                return SkillResult(True, data=VLMResult(
                    frame=str(frame_path), frame_num=frame_num, prompt=prompt,
                    response=response_text, provider=self.config.provider.value,
                    model=self.config.model, latency_ms=latency
                ))
            else:
                return SkillResult(False, error=f"API {resp.status_code}: {resp.text}")
        except Exception as e:
            return SkillResult(False, error=str(e))
    
    def review_frame(self, frame: Union[str, Path, VLMFrame], prompt: str) -> VLMResult:
        """Convenience method returning VLMResult directly."""
        result = self.execute(frame, prompt)
        if result.success:
            return result.data
        else:
            return VLMResult(
                frame=str(frame), frame_num=None, prompt=prompt,
                response="", provider=self.config.provider.value, model=self.config.model,
                error=result.error
            )
    
    def review_frames(self, frames: List[Union[str, Path, VLMFrame]], 
                      prompt: str) -> List[VLMResult]:
        """Review multiple frames with same prompt."""
        results = []
        for frame in frames:
            result = self.review_frame(frame, prompt)
            results.append(result)
            if result.error:
                print(f"Error on {frame}: {result.error}")
        return results
    
    def load_frames_from_dir(self, frames_dir: Union[str, Path], 
                             pattern: str = "*.png",
                             max_frames: Optional[int] = None,
                             sample_rate: int = 1) -> List[VLMFrame]:
        """Load frames from directory with optional sampling."""
        frames_dir = Path(frames_dir)
        all_frames = sorted(frames_dir.glob(pattern))
        
        if sample_rate > 1:
            all_frames = all_frames[::sample_rate]
        if max_frames:
            all_frames = all_frames[:max_frames]
        
        vlm_frames = []
        for f in all_frames:
            frame_num = None
            try:
                frame_num = int(f.stem.split('_')[-1])
            except:
                pass
            vlm_frames.append(VLMFrame(path=f, frame_num=frame_num))
        return vlm_frames


def create_reviewer(provider: str = "lmstudio", model: str = None, **kwargs) -> VLMReviewerSkill:
    """Factory function to create configured reviewer."""
    provider_enum = VLMProvider(provider.lower())
    config = VLMConfig(provider=provider_enum, **kwargs)
    if model:
        config.model = model
    return VLMReviewerSkill(config)