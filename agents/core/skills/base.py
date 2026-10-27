"""
Base Skill Classes
Provides standardized interfaces for all skills in the monorepo.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List
from abc import ABC, abstractmethod
from pathlib import Path


@dataclass
class SkillConfig:
    """Base configuration for skills."""
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    """Standardized skill execution result."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
        }


class Skill(ABC):
    """
    Base class for all skills.
    
    Skills should implement:
    - name, description, version class attributes
    - execute() method for main functionality
    - Optional: validate_config() for config validation
    """
    
    name: str = "base_skill"
    description: str = "Base skill class"
    version: str = "1.0.0"
    
    def __init__(self, config: Optional[SkillConfig] = None, **kwargs):
        self.config = config or SkillConfig()
        # Allow kwargs to override config parameters
        for k, v in kwargs.items():
            setattr(self.config, k, v)
        self._validate_config()
    
    def _validate_config(self):
        """Override in subclass for config validation."""
        pass
    
    @abstractmethod
    def execute(self, *args, **kwargs) -> SkillResult:
        """Main execution method. Override in subclass."""
        pass
    
    def run(self, *args, **kwargs) -> SkillResult:
        """Public run method with error handling."""
        try:
            return self.execute(*args, **kwargs)
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"{self.name}: {type(e).__name__}: {e}",
                metadata={"exception_type": type(e).__name__}
            )


# Utility functions
def load_skill_config(config_path: Union[str, Path]) -> SkillConfig:
    """Load skill config from YAML file."""
    import yaml
    config_path = Path(config_path)
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return SkillConfig(**data)


def discover_skills(skills_dir: Union[str, Path]) -> List[str]:
    """Discover skill modules in a directory."""
    skills_dir = Path(skills_dir)
    skills = []
    for item in skills_dir.iterdir():
        if item.is_dir() and (item / "__init__.py").exists():
            skills.append(item.name)
    return skills