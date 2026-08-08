"""Base class for artifact renderers."""
from abc import ABC, abstractmethod


class ArtifactRenderer(ABC):
    @abstractmethod
    def render(self, data: dict) -> str:
        """Convert artifact data to a readable text block."""
        pass
