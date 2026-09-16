import asyncio
import difflib
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from typing import Any

from dotenv import load_dotenv

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


def three_way_merge(base_text: str, ai_text: str, user_text: str) -> str:
    """Performs a deterministic 3-way line merge between base snapshot, AI edits, and concurrent user edits.

    base_text: Code snapshot when worker task started.
    ai_text: Code modified by Antigravity worker.
    user_text: Latest active editor code including any concurrent user edits.
    """
    if user_text == base_text:
        return ai_text
    if ai_text == base_text:
        return user_text
    if ai_text == user_text:
        return user_text

    base_lines = base_text.splitlines(keepends=True)
    ai_lines = ai_text.splitlines(keepends=True)
    user_lines = user_text.splitlines(keepends=True)

    ai_matcher = difflib.SequenceMatcher(None, base_lines, ai_lines)
    user_matcher = difflib.SequenceMatcher(None, base_lines, user_lines)

    ai_ops = [op for op in ai_matcher.get_opcodes() if op[0] != "equal"]
    user_ops = [op for op in user_matcher.get_opcodes() if op[0] != "equal"]

    # Collect change chunks: (base_start, base_end, 'user' | 'ai', replacement_lines)
    changes: list[tuple[int, int, str, list[str]]] = []
    for _tag, i1, i2, j1, j2 in user_ops:
        changes.append((i1, i2, "user", user_lines[j1:j2]))
    for _tag, i1, i2, j1, j2 in ai_ops:
        changes.append((i1, i2, "ai", ai_lines[j1:j2]))

    # Sort changes by base_start; user insertions at same line come first
    changes.sort(key=lambda c: (c[0], 0 if c[2] == "user" else 1, c[1]))

    merged_lines: list[str] = []
    curr_base = 0

    for i1, i2, _source, rep in changes:
        if i1 > curr_base:
            merged_lines.extend(base_lines[curr_base:i1])
            curr_base = i1
        if i1 >= curr_base:
            merged_lines.extend(rep)
            curr_base = max(curr_base, i2)
        else:
            # Overlap handling
            if i2 > curr_base:
                merged_lines.extend(base_lines[curr_base:i2])
                curr_base = i2

    if curr_base < len(base_lines):
        merged_lines.extend(base_lines[curr_base:])

    return "".join(merged_lines)


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
            api_key or os.getenv("ANTIGRAVITY_API_KEY") or os.getenv("GEMINI_API_KEY")
        )
        # If model is not explicitly provided or in env, leave as None to use SDK default (gemini-3.7-flash)
        self.model = (
            model or os.getenv("ANTIGRAVITY_MODEL") or os.getenv("GEMINI_FLASH_MODEL")
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
            project or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("VERTEX_PROJECT")
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
                    "You are Gemini: Player 2, a fast and agile AI pair programmer and game designer. "
                    "The active game code is located in 'breakout.js' in your workspace. "
                    "Apply code modifications directly to 'breakout.js' using edit_file. "
                    "Be concise, fast, and surgical with your changes. "
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
                    "Apply the requested code changes directly to 'breakout.js' using edit_file."
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
                    return CodeDiffEvent(
                        description=summary,
                        edits=edits,
                        modified_code=modified_code,
                    )

        except Exception as err:
            logger.exception("Error in AntigravityWorker native execution")
            return CodeDiffEvent(
                description=f"Antigravity worker error: {err}",
                edits=[],
            )

        return CodeDiffEvent(
            description=f"Failed to execute task: {instruction}", edits=[]
        )
