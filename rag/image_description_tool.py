"""
Ollama vision description helper for APOEMA's plot analysis (ollama fallback).

Calls the Ollama vision model (qwen2.5vl:3b by default) directly with a
base64-encoded PNG, because CrewAI's OpenAI-compatible Ollama provider does not
convert ImageFile input_files into multimodal message content. This bridges that
gap so vision-capable tasks can interpret chart images in the standard CrewAI
flow.

Hosted models (e.g. gemini) see the image natively via task input_files
(multimodal), so this helper is only exercised on the ollama path.
"""

import base64
import json
import logging
import os
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


def describe_image(image_path: str) -> str:
    """Describe a chart image using the local Ollama vision model.

    Args:
        image_path: Path to the chart image (PNG).

    Returns:
        Text description of the image contents, or an error message.
    """
    path = Path(image_path)
    if not path.exists():
        return (
            f"Error: image file not found at {image_path or '(no path set)'}. "
            "Ensure the image exists and the path is correct."
        )

    prompt = (
        "Descreva detalhadamente este gráfico/visualização em português. Inclua: "
        "título exato, tipo de gráfico, rótulos e unidades dos eixos, legenda, "
        "valores aproximados dos dados, layout e a mensagem principal."
    )

    try:
        img_b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        host = os.getenv(
            "OLLAMA_HOST",
            os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )
        vision_model = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:3b")

        payload = json.dumps({
            "model": vision_model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        result = data.get("response", "")
        if not result:
            return "Error: vision model returned empty response"
        return result

    except Exception as e:
        error_msg = f"Image description failed: {e}"
        logger.error(error_msg)
        return error_msg
