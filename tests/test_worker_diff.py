from backend.worker import AntigravityWorker


def test_three_way_merge_user_inserted_lines_above():
    from backend.session import apply_code_edits
    from backend.worker import compute_diff_chunks, three_way_merge

    base = "let score = 0;\nlet lives = 3;\nlet ball = { color: '#f43f5e' };\n"
    # AI modifies ball color on line 3 of base
    ai = "let score = 0;\nlet lives = 3;\nlet ball = { color: '#fbbf24' };\n"
    # User concurrently inserted 2 header lines at line 1
    user = "// Game config\nlet maxLives = 5;\nlet score = 0;\nlet lives = 3;\nlet ball = { color: '#f43f5e' };\n"

    merged = three_way_merge(base_text=base, ai_text=ai, user_text=user)
    assert "// Game config\n" in merged
    assert "let maxLives = 5;\n" in merged
    assert "let score = 0;\n" in merged
    assert "color: '#fbbf24'" in merged

    # Compute surgical diffs against user's current editor
    rebased_chunks = compute_diff_chunks(user, merged)
    assert len(rebased_chunks) == 1
    # Line number must be 5 (where ball is in user code), NOT line 3!
    assert rebased_chunks[0].start_line == 5
    assert rebased_chunks[0].end_line == 5

    # Applying rebased chunks to user editor yields merged code cleanly
    applied = apply_code_edits(user, rebased_chunks)
    assert applied == merged


def test_three_way_merge_disjoint_edits():
    from backend.worker import three_way_merge

    base = "line 1\nline 2\nline 3\nline 4\n"
    # AI modifies line 4
    ai = "line 1\nline 2\nline 3\nline 4 [AI modified]\n"
    # User modifies line 1
    user = "line 1 [User modified]\nline 2\nline 3\nline 4\n"

    merged = three_way_merge(base_text=base, ai_text=ai, user_text=user)
    assert "line 1 [User modified]" in merged
    assert "line 2" in merged
    assert "line 3" in merged
    assert "line 4 [AI modified]" in merged


def test_compute_diff_chunks_preserves_indentation_and_case():
    from backend.session import apply_code_edits
    from backend.worker import compute_diff_chunks

    old_code = "function test() {\n    let x = 1;\n}\n"
    new_code = "function test() {\n    switch(x) {\n        case 1:\n            return true;\n    }\n}\n"

    chunks = compute_diff_chunks(old_code, new_code)
    applied = apply_code_edits(old_code, chunks)
    assert applied == new_code
    assert "case 1:" in applied


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
        assert (
            "no changes" in res.description.lower()
            or "unchanged" in res.description.lower()
        )
        assert len(res.edits) == 0


def test_worker_execute_task_honest_on_exception():
    import asyncio
    from unittest.mock import patch

    worker = AntigravityWorker(api_key="mock-key")

    with patch(
        "google.antigravity.Agent", side_effect=RuntimeError("API quota exceeded")
    ):
        res = asyncio.run(worker.execute_task("make ball faster", "let speed = 5;\n"))
        # Must NOT claim "Task completed"
        assert "Task completed" not in res.description
        assert "error" in res.description.lower() or "failed" in res.description.lower()
        assert len(res.edits) == 0
