import json
import logging
import os
import re
from collections.abc import Awaitable, Callable

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from backend.models import CodeDiffEvent, DiffChunk

load_dotenv()
logger = logging.getLogger(__name__)


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


class AntigravityWorker:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = (
            api_key or os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
        )
        self.base_url = (
            base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("GEMINI_BASE_URL")
        )
        self.model = os.getenv("GEMINI_FLASH_MODEL", "gemini-3.8-flash")

    async def execute_task(
        self,
        instruction: str,
        current_code: str,
        on_thought: Callable[[str], Awaitable[None]] | None = None,
    ) -> CodeDiffEvent:
        """Executes a coding task, streaming thoughts and returning surgical edits."""
        logger.info(
            f"Antigravity worker executing task: '{instruction}' using model '{self.model}'"
        )

        code_lines = current_code.splitlines()
        numbered_code = "\n".join(
            f"{i + 1}: {line}" for i, line in enumerate(code_lines)
        )

        prompt = f"""Current Code:
```javascript
{numbered_code}
```

Task: {instruction}

Analyze the code and produce the minimal surgical edits (start_line, end_line, new_text) to accomplish the task.
CRITICAL INSTRUCTIONS:
- The code above displays 1-indexed line numbers (e.g. "183:   initBricks();").
- start_line and end_line must match the exact 1-indexed line numbers of the code to replace (inclusive).
- In new_text, provide ONLY the clean replacement code without any line number prefixes.
- Replace only the minimal necessary lines.

Output ONLY valid JSON:
{{
  "summary": "brief summary",
  "edits": [
    {{
      "start_line": <int>,
      "end_line": <int>,
      "new_text": "<string>",
      "description": "<string>"
    }}
  ]
}}
"""

        # 1. Try custom REST endpoint if base_url is configured
        if self.base_url:
            try:
                headers = {"Content-Type": "application/json"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"

                endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": WORKER_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": True,
                }

                raw_text_chunks: list[str] = []
                async with (
                    httpx.AsyncClient(timeout=60.0) as client,
                    client.stream(
                        "POST", endpoint, headers=headers, json=payload
                    ) as response,
                ):
                    if response.status_code != 200:
                        err_body = await response.aread()
                        logger.error(
                            f"REST endpoint returned status {response.status_code}: {err_body.decode()}"
                        )
                    else:
                        async for line in response.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                choices = chunk.get("choices", [])
                                if not choices:
                                    continue
                                delta = choices[0].get("delta", {})

                                # Stream reasoning thoughts if returned by model
                                reasoning = delta.get("reasoning_content") or delta.get(
                                    "thinking"
                                )
                                if reasoning and on_thought:
                                    await on_thought(reasoning)

                                content = delta.get("content")
                                if content:
                                    raw_text_chunks.append(content)
                            except Exception as e:  # noqa: BLE001
                                logger.debug(f"Error parsing chunk: {e}")

                raw_text = "".join(raw_text_chunks)
                if raw_text:
                    logger.info(f"Worker raw output: {raw_text[:200]}...")
                    return self._parse_diff_output(raw_text, current_code)

            except Exception as pe:  # noqa: BLE001
                logger.warning(f"Error calling custom endpoint: {pe}")

        # 2. Try Google Antigravity SDK natively
        try:
            from google.antigravity import Agent, LocalAgentConfig

            config = LocalAgentConfig(
                model=self.model,
                api_key=self.api_key,
                system_instructions=WORKER_SYSTEM_PROMPT,
            )
            async with Agent(config) as agent:
                response = await agent.chat(prompt)

                if on_thought:
                    try:
                        async for thought in response.thoughts:
                            if thought:
                                await on_thought(thought)
                    except Exception as te:  # noqa: BLE001
                        logger.warning(f"Error while reading thought stream: {te}")

                raw_text = await response.text()
                logger.info(
                    f"Worker raw output from Antigravity SDK: {raw_text[:200]}..."
                )
                return self._parse_diff_output(raw_text, current_code)

        except Exception:
            logger.exception("Error in AntigravityWorker native execution")

        return CodeDiffEvent(description=f"Task completed: {instruction}", edits=[])

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
            return CodeDiffEvent(description="Unable to parse surgical diff", edits=[])
