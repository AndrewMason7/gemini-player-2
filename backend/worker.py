import asyncio
import difflib
import json
import logging
import os
import re
import tempfile
from collections.abc import Awaitable, Callable
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from backend.models import CodeDiffEvent, DiffChunk

load_dotenv()
logger = logging.getLogger(__name__)


def compute_diff_chunks(old_code: str, new_code: str) -> list[DiffChunk]:
    """Deterministically compute surgical DiffChunks between old and new code.

    Produces 1-indexed line replacement ranges compatible with Monaco executeEdits
    and apply_code_edits.
    """
    old_lines = old_code.splitlines(keepends=True)
    new_lines = new_code.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    chunks: list[DiffChunk] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        new_text = "".join(new_lines[j1:j2])

        if tag == "insert":
            if i1 < len(old_lines):
                # Replace line i1+1 with new_text + original line i1+1
                chunks.append(
                    DiffChunk(
                        start_line=i1 + 1,
                        end_line=i1 + 1,
                        new_text=new_text + old_lines[i1],
                    )
                )
            elif old_lines:
                # Append to end of file
                prefix = "" if old_lines[-1].endswith("\n") else "\n"
                chunks.append(
                    DiffChunk(
                        start_line=len(old_lines),
                        end_line=len(old_lines),
                        new_text=old_lines[-1] + prefix + new_text,
                    )
                )
            else:
                chunks.append(
                    DiffChunk(
                        start_line=1,
                        end_line=1,
                        new_text=new_text,
                    )
                )
        elif tag == "delete":
            chunks.append(
                DiffChunk(
                    start_line=i1 + 1,
                    end_line=i2,
                    new_text="",
                )
            )
        elif tag == "replace":
            chunks.append(
                DiffChunk(
                    start_line=i1 + 1,
                    end_line=i2,
                    new_text=new_text,
                )
            )

    return chunks


class EditSpec(BaseModel):
    start_line: int = Field(description="1-indexed starting line to replace")
    end_line: int = Field(description="1-indexed ending line to replace (inclusive)")
    new_text: str = Field(description="Exact new code replacement")
    description: str = Field(description="Explanation of the edit")


class CodeWorkerResult(BaseModel):
    summary: str = Field(description="One-sentence description of what was changed")
    edits: list[EditSpec] = Field(description="List of surgical line edits")


WORKER_SYSTEM_PROMPT = """You are Gemini: Player 2, an elite real-time AI pair programmer and game designer.
When given the current code and an instruction:
1. Think deeply about the requested change (physics, gameplay, visual aesthetics, bug fixes).
2. Produce SURGICAL edits using 1-indexed line numbers. Only replace the lines that need changing.
3. The code provided is formatted with 1-indexed line numbers (e.g. "15:   speed: 5,"). Use these exact line numbers for start_line and end_line.
4. In "new_text", output ONLY the raw replacement code without any line number prefixes.
5. Keep changes tight, modular, and cleanly formatted for standard JavaScript/HTML canvas.
6. Output valid JSON conforming to:
{
  "summary": "Brief description of changes",
  "edits": [
    {
      "start_line": 15,
      "end_line": 18,
      "new_text": "  speed: 10,\\n",
      "description": "Increase speed"
    }
  ]
}
"""


def _write_file_sync(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _read_file_sync(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class AntigravityWorker:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        vertex: bool | None = None,
        project: str | None = None,
        location: str | None = None,
    ):
        self.api_key = (
            api_key
            or os.getenv("ANTIGRAVITY_API_KEY")
            or os.getenv("GEMINI_API_KEY")
        )
        # If model is not explicitly provided or in env, leave as None to use SDK default (gemini-3.7-flash)
        self.model = (
            model
            or os.getenv("ANTIGRAVITY_MODEL")
            or os.getenv("GEMINI_FLASH_MODEL")
        )

        # Configure Vertex AI / Enterprise mode if specified or detected from environment
        use_vertex_env = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in (
            "true",
            "1",
        )
        has_vertex_project = bool(
            os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("VERTEX_PROJECT")
        )
        self.vertex = (
            vertex if vertex is not None else (use_vertex_env and has_vertex_project)
        )
        self.project = (
            project
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("VERTEX_PROJECT")
        )
        self.location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "global")

    async def execute_task(
        self,
        instruction: str,
        current_code: str,
        on_thought: Callable[[str], Awaitable[None]] | None = None,
    ) -> CodeDiffEvent:
        """Executes a coding task via Google Antigravity SDK using real workspace file tools."""
        logger.info(
            f"Antigravity worker executing task: '{instruction}' (model: {self.model or 'SDK default'}, vertex: {self.vertex})"
        )

        try:
            from google.antigravity import (
                Agent,
                BuiltinTools,
                LocalAgentConfig,
            )
            from google.antigravity.types import CapabilitiesConfig

            with tempfile.TemporaryDirectory() as temp_dir:
                file_path = os.path.join(temp_dir, "breakout.js")
                await asyncio.to_thread(_write_file_sync, file_path, current_code)

                system_instruction = (
                    "You are Gemini: Player 2, an elite AI pair programmer and game designer. "
                    "The active game code is located in 'breakout.js' in your workspace. "
                    "Always inspect 'breakout.js' using view_file and apply code modifications directly using edit_file. "
                    "Do not just explain what needs to be changed—always write the changes to 'breakout.js'. "
                    "Keep changes clean, modular, and working for HTML5 canvas JavaScript."
                )

                capabilities = CapabilitiesConfig(
                    enabled_tools=[BuiltinTools.VIEW_FILE, BuiltinTools.EDIT_FILE]
                )

                config_kwargs: dict[str, Any] = {
                    "model": self.model,
                    "workspaces": [temp_dir],
                    "capabilities": capabilities,
                    "system_instructions": system_instruction,
                }

                if self.vertex:
                    config_kwargs["vertex"] = True
                    if self.project and self.location:
                        # Standard Mode (ADC)
                        config_kwargs["project"] = self.project
                        config_kwargs["location"] = self.location
                    elif self.api_key:
                        # Express Mode (API Key)
                        config_kwargs["api_key"] = self.api_key
                else:
                    if self.api_key:
                        config_kwargs["api_key"] = self.api_key

                config = LocalAgentConfig(**config_kwargs)

                task_prompt = (
                    f"Task: {instruction}\n\n"
                    "Apply the necessary code changes directly to 'breakout.js' using edit_file."
                )

                async with Agent(config) as agent:
                    response = await agent.chat(task_prompt)

                    if on_thought:
                        try:
                            async for thought in response.thoughts:
                                if thought:
                                    await on_thought(thought)
                        except Exception as te:  # noqa: BLE001
                            logger.warning(f"Error while reading thought stream: {te}")

                    # Read back the modified file from the workspace
                    modified_code = await asyncio.to_thread(_read_file_sync, file_path)

                    if modified_code == current_code:
                        logger.warning(
                            f"Antigravity worker left breakout.js unchanged for '{instruction}'"
                        )
                        return CodeDiffEvent(
                            description=f"Antigravity worker made no changes to breakout.js for: {instruction}",
                            edits=[],
                        )

                    edits = compute_diff_chunks(current_code, modified_code)
                    summary = f"Applied code changes: {instruction}"
                    logger.info(
                        f"Antigravity worker produced {len(edits)} diff chunk(s) for '{instruction}'"
                    )
                    return CodeDiffEvent(description=summary, edits=edits)

        except Exception as err:
            logger.exception("Error in AntigravityWorker native execution")
            return CodeDiffEvent(
                description=f"Antigravity worker error: {err}",
                edits=[],
            )

        return CodeDiffEvent(
            description=f"Failed to execute task: {instruction}", edits=[]
        )

    def _parse_diff_output(self, raw_text: str, current_code: str) -> CodeDiffEvent:
        """Robustly parses JSON from LLM response or code block."""
        cleaned = raw_text.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(cleaned, strict=False)
            edits = []
            for item in data.get("edits", []):
                start_l = max(1, int(item.get("start_line", 1)))
                end_l = max(start_l, int(item.get("end_line", start_l)))
                raw_new_text = str(item.get("new_text", ""))

                # Strip accidental echoed line numbers (e.g. "183:   initBricks();")
                cleaned_lines = []
                for line in raw_new_text.splitlines(keepends=True):
                    m = re.match(r"^\s*(\d+):\s?(.*)", line)
                    if m and not line.strip().startswith(("case ", "http:", "https:")):
                        line_num = int(m.group(1))
                        if abs(line_num - start_l) <= 5 or abs(line_num - end_l) <= 5:
                            cleaned_lines.append(
                                m.group(2) + ("\n" if line.endswith("\n") else "")
                            )
                            continue
                    cleaned_lines.append(line)
                clean_new_text = "".join(cleaned_lines)

                edits.append(
                    DiffChunk(
                        start_line=start_l,
                        end_line=end_l,
                        new_text=clean_new_text,
                        description=str(item.get("description", "")),
                    )
                )
            return CodeDiffEvent(
                description=data.get("summary", "Applied code edits"), edits=edits
            )
        except Exception as err:  # noqa: BLE001
            logger.warning(
                f"Failed to parse structured diff JSON: {err}. Raw was: {cleaned}"
            )
            return CodeDiffEvent(
                description=f"Unable to parse surgical diff: {err}", edits=[]
            )
