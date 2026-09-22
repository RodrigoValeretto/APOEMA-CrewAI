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
            # The server default is OLLAMA_CONTEXT_LENGTH (16384 for the text
            # model), but qwen2.5vl with a 16K window costs ~6GB of RAM and
            # OOM-killed the llama-server mid-analysis in the 7.65GB Docker VM
            # (2026-09-09). Verified 2026-09-09: num_ctx=4096 TRUNCATES the
            # vision response ("O gr" instead of the full 2K-char description,
            # which then makes task 7 hallucinate "hypothetical" chart data);
            # 8192 produces the full description at ~same RAM as 12288/16384.
            # num_predict caps the generation: without it qwen2.5vl kept
            # emitting until the 8192-token window was full (~4K tokens at
            # ~3 tok/s ≈ 23 min on CPU), blowing past this call's 600s timeout
            # while llama-server kept generating in the background — the
            # analysis stalled in `processing` (2026-09-11, analyses 117/119).
            # Verified the same day: the same chart returns a complete, correct
            # description in 203s / 600 tokens / 1959 chars with the cap.
            "options": {
                "num_ctx": 8192,
                "num_predict": int(os.getenv("OLLAMA_VISION_MAX_TOKENS", "600")),
            },
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
