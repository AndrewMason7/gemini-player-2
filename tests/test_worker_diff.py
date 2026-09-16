from backend.worker import AntigravityWorker


def test_parse_diff_output_markdown_fence():
    worker = AntigravityWorker(api_key="mock-key")
    raw_response = """Here are the requested surgical edits:
```json
{
  "summary": "Increased ball speed and paddle width",
  "edits": [
    {
      "start_line": 15,
      "end_line": 16,
      "new_text": "  speed: 10,\n",
      "description": "Bump speed"
    }
  ]
}
```
"""
    diff_event = worker._parse_diff_output(raw_response, "")
    assert diff_event.type == "code_diff"
    assert diff_event.description == "Increased ball speed and paddle width"
    assert len(diff_event.edits) == 1
    assert diff_event.edits[0].start_line == 15
    assert diff_event.edits[0].new_text == "  speed: 10,\n"


def test_parse_diff_output_raw_json():
    worker = AntigravityWorker(api_key="mock-key")
    raw_response = """{"summary": "Added laser powerup", "edits": [{"start_line": 40, "end_line": 42, "new_text": "  laser: true\n"}]}"""
    diff_event = worker._parse_diff_output(raw_response, "")
    assert diff_event.description == "Added laser powerup"
    assert len(diff_event.edits) == 1
    assert diff_event.edits[0].start_line == 40


def test_parse_diff_output_strips_echoed_line_numbers():
    worker = AntigravityWorker(api_key="mock-key")
    raw_response = """{
      "summary": "Reset bricks on game reset",
      "edits": [
        {
          "start_line": 183,
          "end_line": 184,
          "new_text": "183:   initBricks();\\n184:   resetBall();\\n",
          "description": "Initialize bricks"
        }
      ]
    }"""
    diff_event = worker._parse_diff_output(raw_response, "")
    assert len(diff_event.edits) == 1
    assert diff_event.edits[0].new_text == "  initBricks();\n  resetBall();\n"


def test_parse_diff_output_preserves_case_statements():
    worker = AntigravityWorker(api_key="mock-key")
    raw_response = """{
      "summary": "Added switch statement",
      "edits": [
        {
          "start_line": 50,
          "end_line": 52,
          "new_text": "  switch(level) {\\n    case 1:\\n      speed = 10;\\n      break;\\n  }\\n",
          "description": "Switch logic"
        }
      ]
    }"""
    diff_event = worker._parse_diff_output(raw_response, "")
    assert len(diff_event.edits) == 1
    assert "case 1:" in diff_event.edits[0].new_text


def test_compute_diff_chunks_single_line_replacement():
    from backend.session import apply_code_edits
    from backend.worker import compute_diff_chunks

    old_code = "line 1\ncolor: #f43f5e\nline 3\n"
    new_code = "line 1\ncolor: #fbbf24\nline 3\n"
    chunks = compute_diff_chunks(old_code, new_code)
    assert len(chunks) == 1
    assert chunks[0].start_line == 2
    assert chunks[0].end_line == 2
    assert chunks[0].new_text == "color: #fbbf24\n"

    applied = apply_code_edits(old_code, chunks)
    assert applied == new_code


def test_compute_diff_chunks_insertion_and_deletion():
    from backend.session import apply_code_edits
    from backend.worker import compute_diff_chunks

    old_code = "A\nB\nC\nD\n"
    # Delete B, insert X and Y
    new_code = "A\nX\nY\nC\nD\nZ\n"
    chunks = compute_diff_chunks(old_code, new_code)
    applied = apply_code_edits(old_code, chunks)
    assert applied == new_code


def test_worker_execute_task_honest_on_unchanged_code():
    import asyncio
    from unittest.mock import AsyncMock, patch

    from backend.worker import AntigravityWorker

    worker = AntigravityWorker(api_key="mock-key")

    # Mock Agent leaving file unchanged
    mock_agent = AsyncMock()
    mock_response = AsyncMock()
    mock_response.thoughts = AsyncMock()
    mock_agent.chat = AsyncMock(return_value=mock_response)
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    with patch("google.antigravity.Agent", return_value=mock_agent):
        res = asyncio.run(worker.execute_task("make ball faster", "let speed = 5;\n"))
        # Must NOT claim "Task completed"
        assert "Task completed" not in res.description
        assert "no changes" in res.description.lower() or "unchanged" in res.description.lower()
        assert len(res.edits) == 0


def test_worker_execute_task_honest_on_exception():
    import asyncio
    from unittest.mock import patch

    from backend.worker import AntigravityWorker

    worker = AntigravityWorker(api_key="mock-key")

    with patch("google.antigravity.Agent", side_effect=RuntimeError("API quota exceeded")):
        res = asyncio.run(worker.execute_task("make ball faster", "let speed = 5;\n"))
        # Must NOT claim "Task completed"
        assert "Task completed" not in res.description
        assert "error" in res.description.lower() or "failed" in res.description.lower()
        assert len(res.edits) == 0

