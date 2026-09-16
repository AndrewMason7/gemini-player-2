import json
import re
import shutil
import subprocess

from backend.constants import DEFAULT_BREAKOUT_CODE
from backend.models import DiffChunk
from backend.session import apply_code_edits
from backend.worker import AntigravityWorker


def test_ball_actually_turns_gold_result():
    """Verifies that applying a surgical edit targeting the ball color line (line 105)
    in DEFAULT_BREAKOUT_CODE actually changes the ball color from '#f43f5e' to gold ('#fbbf24')
    while preserving the rest of the game code integrity.
    """
    lines_before = DEFAULT_BREAKOUT_CODE.splitlines()
    assert 'color: "#f43f5e"' in lines_before[104], (
        "Line 105 must originally be the crimson ball color"
    )

    gold_edit = DiffChunk(
        start_line=105,
        end_line=105,
        new_text='  color: "#fbbf24",\n',
        description="Change ball color to vibrant gold",
    )

    new_code = apply_code_edits(DEFAULT_BREAKOUT_CODE, [gold_edit])
    lines_after = new_code.splitlines()

    # Verify line 105 is now gold
    assert 'color: "#fbbf24"' in lines_after[104]
    assert 'color: "#f43f5e"' not in new_code

    # Verify ball object structure is preserved
    ball_match = re.search(r"let ball\s*=\s*\{([^}]+)\};", new_code)
    assert ball_match is not None
    ball_body = ball_match.group(1)
    assert 'color: "#fbbf24"' in ball_body
    assert "radius: 6" in ball_body
    assert "speed: 5.5" in ball_body

    # If bun or node is installed, verify the JavaScript actually runs and ball.color is gold
    js_runtime = shutil.which("bun") or shutil.which("node")
    if js_runtime:
        code_json = json.dumps(new_code + "\nreturn ball;\n")
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
console.log("BALL_COLOR_VERIFIED:" + b.color);
"""
        proc = subprocess.run(
            [js_runtime, "-e", eval_script],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"JS execution failed: {proc.stderr}"
        assert "BALL_COLOR_VERIFIED:#fbbf24" in proc.stdout


def test_worker_diff_parsing_and_ball_gold_application():
    """Verifies that an AntigravityWorker LLM response turning the ball gold
    is correctly parsed into DiffChunk and mutates DEFAULT_BREAKOUT_CODE to gold.
    """
    worker = AntigravityWorker(api_key="mock-key")
    raw_llm_response = """I have updated the ball's color to vibrant gold with a glowing trail.
```json
{
  "summary": "Change ball color to vibrant gold",
  "edits": [
    {
      "start_line": 105,
      "end_line": 105,
      "new_text": "  color: \\"#fbbf24\\",\\n",
      "description": "Gold ball color"
    }
  ]
}
```"""
    diff_event = worker._parse_diff_output(raw_llm_response, DEFAULT_BREAKOUT_CODE)
    assert len(diff_event.edits) == 1
    assert diff_event.edits[0].start_line == 105

    edited_code = apply_code_edits(DEFAULT_BREAKOUT_CODE, diff_event.edits)
    assert 'color: "#fbbf24"' in edited_code
    assert 'color: "#f43f5e"' not in edited_code
