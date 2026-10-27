"""
Core VLM (Vision-Language Model) Skills
Shared VLM reviewer functionality for all projects.
"""
from .vlm_reviewer import VLMReviewerSkill, VLMConfig, VLMProvider, VLMFrame, VLMResult
from .config import VLMConfig as VLMConfigV2, VLMProvider as VLMProviderV2

__all__ = [
    "VLMReviewerSkill",
    "VLMConfig", 
    "VLMProvider",
    "VLMFrame",
    "VLMResult",
    "create_reviewer",
]

# Re-export with simpler names
from .vlm_reviewer import create_reviewer