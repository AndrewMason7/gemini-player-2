import asyncio
import json
import os
import shutil

import pytest

from backend.conductor import LiveConductor
from backend.constants import DEFAULT_BREAKOUT_CODE
from backend.worker import AntigravityWorker

RUN_LIVE = bool(os.getenv("RUN_LIVE_AGENTS") == "1" and os.getenv("GEMINI_API_KEY"))


@pytest.mark.skipif(
    not RUN_LIVE,
    reason="Gated live test. Set RUN_LIVE_AGENTS=1 and GEMINI_API_KEY to run.",
)
@pytest.mark.anyio
async def test_live_antigravity_agent_gold_ball():
    """Live integration test: Prompts real Google Antigravity Agent (gemini-3.7-flash)
    with a workspace containing breakout.js to change the ball color to '#fbbf24'.
    Verifies that the model actually edits the file, diffs are generated, and
    executing the modified JavaScript produces ball.color == '#fbbf24'.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    worker = AntigravityWorker(api_key=api_key)

    result = await worker.execute_task(
        instruction="Change the ball color property in breakout.js to gold '#fbbf24'",
        current_code=DEFAULT_BREAKOUT_CODE,
    )

    assert result is not None, "Live worker must return a CodeDiffEvent"
    assert len(result.edits) > 0, "Live worker must generate at least one DiffChunk"
    assert result.modified_code is not None
    assert (
        'color: "#fbbf24"' in result.modified_code
        or "color: '#fbbf24'" in result.modified_code
    )

    # Verify that the modified JavaScript executes cleanly and ball.color is gold
    js_runtime = shutil.which("bun") or shutil.which("node")
    if js_runtime:
        code_json = json.dumps(result.modified_code + "\nreturn ball;\n")
        eval_script = f"""
const ctx = new Proxy({{}}, {{ get: () => () => ({{}}) }});
const canvas = {{ getContext: () => ctx, width: 480, height: 320, addEventListener: () => {{}} }};
globalThis.document = {{ getElementById: () => canvas, addEventListener: () => {{}} }};
globalThis.window = {{ addEventListener: () => {{}} }};
globalThis.requestAnimationFrame = () => {{}};
globalThis.localStorage = {{ getItem: () => "0", setItem: () => {{}} }};

const run = new Function({code_json});
const b = run();
if (b.color !== "#fbbf24") {{
    console.error("Expected #fbbf24, got " + b.color);
    process.exit(1);
}}
console.log("LIVE_BALL_COLOR_VERIFIED:" + b.color);
"""
        proc = await asyncio.create_subprocess_exec(
            js_runtime,
            "-e",
            eval_script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        assert proc.returncode == 0, f"JS execution failed: {stderr.decode()}"
        assert "LIVE_BALL_COLOR_VERIFIED:#fbbf24" in stdout.decode()


@pytest.mark.skipif(
    not RUN_LIVE,
    reason="Gated live test. Set RUN_LIVE_AGENTS=1 and GEMINI_API_KEY to run.",
)
@pytest.mark.anyio
async def test_live_conductor_websocket_handshake():
    """Live integration test: Connects LiveConductor to Gemini Live API (gemini-3.8-live)
    over real WebSockets, sends text greeting, and verifies session establishment.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    transcripts = []

    async def on_transcript(sender: str, text: str):
        transcripts.append((sender, text))

    conductor = LiveConductor(
        api_key=api_key,
        model="gemini-3.8-live",
        on_transcript=on_transcript,
    )

    connected = await conductor.connect()
    assert connected is True, "Must successfully connect to Gemini Live WebSockets"
    assert conductor.is_live is True

    await conductor.close()
    assert conductor.is_running is False
