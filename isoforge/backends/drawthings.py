"""Draw Things HTTP API (verified live: POST /sdapi/v1/txt2img -> {"images":[b64]})."""
import base64
import io

import requests
from PIL import Image

from .base import Backend, BackendError


class DrawThings(Backend):
    name = "drawthings"

    def __init__(self, url: str, timeout: int = 900):
        self.url, self.timeout = url.rstrip("/"), timeout

    def check(self) -> dict:
        try:
            o = requests.get(self.url + "/sdapi/v1/options", timeout=5).json()
            return {"ok": True, "detail": f"model={o.get('model')} steps={o.get('steps')}"}
        except Exception as e:
            return {"ok": False, "detail": f"Draw Things API unreachable at {self.url}: {e}. "
                    "Enable Settings > Advanced > API Server (protocol HTTP, TLS off)."}

    def txt2img(self, prompt, negative, seed, style, size=None):
        size = size or style.get("size", 1024)
        body = {"prompt": prompt, "negative_prompt": negative, "seed": seed,
                "steps": style.get("steps", 30), "guidance_scale": style.get("cfg", 4),
                "width": size, "height": size}
        if style.get("lora"):
            body["loras"] = [{"file": style["lora"], "weight": style.get("lora_strength", 0.6)}]
        try:
            r = requests.post(self.url + "/sdapi/v1/txt2img", json=body, timeout=self.timeout)
            r.raise_for_status()
            return Image.open(io.BytesIO(base64.b64decode(r.json()["images"][0]))).convert("RGB")
        except Exception as e:
            raise BackendError(f"Draw Things txt2img failed: {e}") from e
