from abc import ABC, abstractmethod
from PIL import Image


class BackendError(RuntimeError):
    pass


class Backend(ABC):
    name = "base"

    @abstractmethod
    def check(self) -> dict:
        """Return {'ok': bool, 'detail': str}; never raise."""

    @abstractmethod
    def txt2img(self, prompt: str, negative: str, seed: int, style: dict, size: int | None = None) -> Image.Image:
        ...
