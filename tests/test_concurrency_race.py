import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models import CodeDiffEvent, DiffChunk
from backend.session import LiveSessionManager


@pytest.mark.anyio
async def test_overlapping_voice_command_and_user_edit():
    """Verifies that when a user edits an unrelated line in Monaco (via editor_sync)
    WHILE an Antigravity worker voice modification task is in-flight, both changes
    coexist in session.current_code without the worker clobbering the user's manual edit.
    """
    mock_ws = AsyncMock()
    mock_conductor = MagicMock()
    mock_conductor.update_code = MagicMock()
    mock_conductor.notify_task_completed = AsyncMock()

    initial_code = (
        "let score = 0;\n"
        "let lives = 3;\n"
        "// game config\n"
        "let ball = {\n"
        '  color: "#f43f5e",\n'
        "  speed: 5\n"
        "};\n"
    )

    worker_started = asyncio.Event()
    user_edited = asyncio.Event()

    async def delayed_worker_task(instruction, current_code, on_thought=None):
        worker_started.set()
        # Wait until user makes their edit during worker execution
        await user_edited.wait()
        await asyncio.sleep(0.01)
        # Returns surgical edit changing ball color on line 5
        return CodeDiffEvent(
            description="Changed ball color to gold",
            edits=[
                DiffChunk(
                    start_line=5,
                    end_line=5,
                    new_text='  color: "#fbbf24",\n',
                    description="Turn ball gold",
                )
            ],
        )

    mock_worker = MagicMock()
    mock_worker.execute_task = AsyncMock(side_effect=delayed_worker_task)

    session = LiveSessionManager(
        websocket=mock_ws,
        initial_code=initial_code,
        worker=mock_worker,
    )
    session.conductor = mock_conductor

    # 1. Voice command arrives: dispatches worker task
    dispatch_task = asyncio.create_task(session.on_dispatch_task("make ball gold", ""))

    # 2. Wait for worker to start executing
    await worker_started.wait()

    # 3. User simultaneously types in Monaco, changing line 1: score = 999;
    user_modified_code = (
        "let score = 999;\n"
        "let lives = 3;\n"
        "// game config\n"
        "let ball = {\n"
        '  color: "#f43f5e",\n'
        "  speed: 5\n"
        "};\n"
    )
    await session.handle_client_message(
        {"text": json.dumps({"type": "editor_sync", "code": user_modified_code})}
    )
    user_edited.set()

    # 4. Wait for worker task to complete
    await dispatch_task
    await asyncio.gather(*list(session.active_worker_tasks))

    # 5. Assert that BOTH changes are present:
    # User's edit on line 1: score = 999
    assert "let score = 999;" in session.current_code
    # Worker's surgical edit on line 5: color = "#fbbf24"
    assert 'color: "#fbbf24"' in session.current_code
    assert 'color: "#f43f5e"' not in session.current_code

    # Conductor mirror was updated with the merged code
    mock_conductor.update_code.assert_called_with(session.current_code)

    # Client was sent the code diff so Monaco can patch without resetting cursor
    sent_json = [json.loads(c[0][0]) for c in mock_ws.send_text.call_args_list]
    diff_msgs = [m for m in sent_json if m.get("type") == "code_diff"]
    assert len(diff_msgs) == 1
    assert diff_msgs[0]["edits"][0]["new_text"] == '  color: "#fbbf24",\n'


@pytest.mark.anyio
async def test_rapid_user_keystrokes_during_worker_execution():
    """Verifies that a burst of editor_sync keystroke events while a worker
    is thinking does not cause state desynchronization or race exceptions.
    """
    mock_ws = AsyncMock()
    mock_conductor = MagicMock()
    mock_conductor.update_code = MagicMock()
    mock_conductor.notify_task_completed = AsyncMock()

    code = "let x = 0;\nlet y = 0;\n"

    async def fake_worker(instruction, current_code, on_thought=None):
        await asyncio.sleep(0.05)
        return CodeDiffEvent(
            description="Patched y",
            edits=[DiffChunk(start_line=2, end_line=2, new_text="let y = 100;\n")],
        )

    mock_worker = MagicMock()
    mock_worker.execute_task = AsyncMock(side_effect=fake_worker)

    session = LiveSessionManager(
        websocket=mock_ws,
        initial_code=code,
        worker=mock_worker,
    )
    session.conductor = mock_conductor

    # Start worker
    worker_task = asyncio.create_task(session.on_dispatch_task("patch y", ""))

    # Simulate 5 rapid keystrokes on line 1
    for val in range(1, 6):
        keystroke_code = f"let x = {val};\nlet y = 0;\n"
        await session.handle_client_message(
            {"text": json.dumps({"type": "editor_sync", "code": keystroke_code})}
        )
        await asyncio.sleep(0.005)

    await worker_task
    await asyncio.gather(*list(session.active_worker_tasks))

    # Final code must contain the last keystroke (x = 5) and the worker edit (y = 100)
    assert "let x = 5;" in session.current_code
    assert "let y = 100;" in session.current_code
