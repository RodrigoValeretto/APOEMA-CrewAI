"""
CrewAI-compatible Image Description tool for APOEMA agents.

Calls the Ollama vision model (qwen2.5vl:3b by default) directly with a base64-
encoded PNG, because CrewAI's OpenAI-compatible Ollama provider does not convert
ImageFile input_files into multimodal message content. This tool bridges that gap
so vision-capable tasks can interpret chart images within the standard CrewAI flow.

The image path is set on the tool instance at creation time (see create_tasks), so
the agent only needs to *invoke* the tool — it never has to transcribe a file path,
which is error-prone for LLMs.
"""

import base64
import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ImageDescriptionInput(BaseModel):
    """Input schema for ImageDescriptionTool.

    `focus` is required so the agent always passes a non-empty argument, which
    CrewAI needs to trigger native tool execution (a tool with only optional
    fields yields empty `{}` args that CrewAI's ollama path does not execute).
    Pass an empty string '' for a full general description.
    """

    focus: str = Field(
        ...,
        description=(
            "Focus hint for the image description. Pass an empty string '' for a "
            "full general description (e.g., 'eixos e valores', 'título e legenda')."
        ),
    )


class ImageDescriptionTool(BaseTool):
    """CrewAI tool that describes a fixed PNG image using a vision-capable Ollama model."""

    name: str = "Describe Image"
    description: str = (
        "This tool CAN see and analyze the chart/graph image (you, the text model, "
        "cannot see images directly). Call this tool to obtain a detailed text "
        "description of the image's visual contents: title, chart type, axes "
        "(labels, units, scale), legend, approximate data values, layout, and the "
        "main visual message. Use this tool whenever you need to understand what a "
        "chart image shows. You may optionally pass a focus hint describing which "
        "aspect to emphasize."
    )
    args_schema: Type[BaseModel] = ImageDescriptionInput

    # Fixed image path — set at task creation time (see create_tasks).
    image_path: str = ""

    def _run(self, focus: str = "") -> str:
        """Call the vision model to describe the fixed image.

        Args:
            focus: Focus/aspect to emphasize (empty string for a full description).

        Returns:
            Text description of the image contents.
        """
        path = Path(self.image_path)
        if not path.exists():
            return (
                f"Error: image file not found at {self.image_path or '(no path set)'}. "
                "Ensure the image exists and the tool was configured with a valid path."
            )

        prompt = (
            "Descreva detalhadamente este gráfico/visualização em português. Inclua: "
            "título exato, tipo de gráfico, rótulos e unidades dos eixos, legenda, "
            "valores aproximados dos dados, layout e a mensagem principal."
        )
        if focus:
            prompt += f"\n\nFoco especial: {focus}"

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

    async def _arun(self, focus: str = "") -> str:
        """Async wrapper — delegates to synchronous _run."""
        return self._run(focus=focus)
