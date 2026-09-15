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
