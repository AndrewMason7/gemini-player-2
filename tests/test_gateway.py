import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "service" in data


def test_starter_code_endpoint():
    response = client.get("/api/starter-code")
    assert response.status_code == 200
    data = response.json()
    assert "code" in data
    assert "gameCanvas" in data["code"]
    assert "paddle" in data["code"]


def test_serves_frontend_app():
    response = client.get("/")
    assert response.status_code == 200
    assert "<!doctype html>" in response.text.lower()


def test_websocket_live_offline_handshake():
    with patch("backend.main.LiveConductor") as MockConductorClass:
        mock_instance = MockConductorClass.return_value
        mock_instance.is_running = False
        mock_instance.is_live = False
        mock_instance.connect = AsyncMock(return_value=False)
        mock_instance.close = AsyncMock()
        mock_instance.update_code = MagicMock()

        with client.websocket_connect("/ws/live") as ws:
            status_msg = ws.receive_json()
            assert status_msg["type"] == "status"
            assert status_msg["state"] == "idle"
            assert "Gemini 3.8 Live Offline" in status_msg["message"]

            # Send editor sync
            ws.send_json({"type": "editor_sync", "code": "console.log('updated');"})


def test_websocket_live_with_mocked_conductor():
    with patch("backend.main.LiveConductor") as MockConductorClass:
        mock_instance = MockConductorClass.return_value
        mock_instance.is_running = True
        mock_instance.is_live = True
        mock_instance.connect = AsyncMock(return_value=True)
        mock_instance.close = AsyncMock()
        mock_instance.send_text = AsyncMock()
        mock_instance.send_audio_chunk = AsyncMock()
        mock_instance.send_audio_stream_end = AsyncMock()
        mock_instance.update_code = MagicMock()

        async def fake_listen_loop():
            await asyncio.sleep(0.01)

        mock_instance.listen_loop = fake_listen_loop

        with client.websocket_connect("/ws/live") as ws:
            status_msg = ws.receive_json()
            assert status_msg["type"] == "status"
            assert status_msg["state"] == "listening"
            assert "Gemini 3.8 Live" in status_msg["message"]

            # Send text input
            ws.send_json({"type": "text_input", "text": "Make ball bounce faster"})

            # Send binary audio chunk (16kHz PCM)
            ws.send_bytes(b"\x00\x01" * 500)

            # Send audio stream end (mic mute)
            ws.send_json({"type": "audio_stream_end"})

            # Send user interrupt
            ws.send_json({"type": "user_interrupt"})
            interrupted_msg = ws.receive_json()
            assert interrupted_msg["type"] == "interrupted"

            # Send editor sync
            ws.send_json({"type": "editor_sync", "code": "// new code"})

            # Send JSON ping with timestamp and receive pong
            ws.send_json({"type": "ping", "timestamp": 123456789})
            pong_msg = ws.receive_json()
            assert pong_msg["type"] == "pong"
            assert pong_msg["timestamp"] == 123456789

            # Send plain string ping and receive pong
            ws.send_text("ping")
            pong_msg2 = ws.receive_json()
            assert pong_msg2["type"] == "pong"


def test_websocket_live_status_forwarding():
    with patch("backend.main.LiveConductor") as MockConductorClass:
        mock_instance = MockConductorClass.return_value
        mock_instance.is_running = True
        mock_instance.is_live = True
        mock_instance.connect = AsyncMock(return_value=True)
        mock_instance.close = AsyncMock()
        mock_instance.update_code = MagicMock()

        captured_callbacks = {}

        def mock_init(*args, **kwargs):
            captured_callbacks.update(kwargs)
            return mock_instance

        MockConductorClass.side_effect = mock_init

        async def fake_listen_loop():
            # Trigger on_status callback
            if "on_status" in captured_callbacks:
                await captured_callbacks["on_status"](
                    "reconnecting", "Reconnecting to upstream..."
                )
            await asyncio.sleep(0.01)

        mock_instance.listen_loop = fake_listen_loop

        with client.websocket_connect("/ws/live") as ws:
            # 1. Initial listening status from main.py
            msg1 = ws.receive_json()
            assert msg1["type"] == "status"
            assert msg1["state"] == "listening"

            # 2. Reconnecting status forwarded from conductor
            msg2 = ws.receive_json()
            assert msg2["type"] == "status"
            assert msg2["state"] == "reconnecting"
            assert "Reconnecting" in msg2["message"]


@pytest.mark.anyio
async def test_session_worker_concurrency_serialization():
    from backend.models import CodeDiffEvent, DiffChunk
    from backend.session import LiveSessionManager

    mock_ws = AsyncMock()
    mock_conductor = MagicMock()
    mock_conductor.update_code = MagicMock()
    mock_conductor.notify_task_completed = AsyncMock()

    call_order = []
    received_codes = []

    async def fake_execute_task(instruction, current_code, on_thought=None):
        call_order.append(f"start_{instruction}")
        received_codes.append(current_code)
        await asyncio.sleep(0.02)
        call_order.append(f"end_{instruction}")
        if instruction == "task1":
            return CodeDiffEvent(
                description="Task 1 applied",
                edits=[
                    DiffChunk(
                        start_line=1,
                        end_line=1,
                        new_text="line 1 modified\n",
                        description="edit 1",
                    )
                ],
            )
        return CodeDiffEvent(
            description="Task 2 applied",
            edits=[
                DiffChunk(
                    start_line=2,
                    end_line=2,
                    new_text="line 2 modified\n",
                    description="edit 2",
                )
            ],
        )

    mock_worker = MagicMock()
    mock_worker.execute_task = AsyncMock(side_effect=fake_execute_task)

    session = LiveSessionManager(
        websocket=mock_ws,
        initial_code="line 1\nline 2\nline 3\n",
        worker=mock_worker,
    )
    session.conductor = mock_conductor

    # Dispatch two tasks concurrently
    await session.on_dispatch_task("task1", "")
    await session.on_dispatch_task("task2", "")

    # Wait for all background worker tasks to finish
    await asyncio.gather(*list(session.active_worker_tasks))

    # Verify serial execution order
    assert call_order == ["start_task1", "end_task1", "start_task2", "end_task2"]

    # Verify task2 received the code updated by task1
    assert "line 1 modified" in received_codes[1]
    assert session.current_code == "line 1 modified\nline 2 modified\nline 3\n"

    # Verify Player 2 cursor flew to edited lines
    sent_msgs = [json.loads(c[0][0]) for c in mock_ws.send_text.call_args_list]
    cursor_msgs = [m for m in sent_msgs if m.get("type") == "cursor_move"]
    assert len(cursor_msgs) == 2
    assert cursor_msgs[0]["line"] == 1
    assert cursor_msgs[0]["gesture"] == "typing"
    assert cursor_msgs[1]["line"] == 2
    assert cursor_msgs[1]["gesture"] == "typing"


@pytest.mark.anyio
async def test_session_empty_edits_calls_notify_task_failed():
    from backend.models import CodeDiffEvent
    from backend.session import LiveSessionManager

    mock_ws = AsyncMock()
    mock_conductor = MagicMock()
    mock_conductor.update_code = MagicMock()
    mock_conductor.notify_task_completed = AsyncMock()
    mock_conductor.notify_task_failed = AsyncMock()

    mock_worker = MagicMock()
    mock_worker.execute_task = AsyncMock(
        return_value=CodeDiffEvent(
            description="Could not parse requested change",
            edits=[],
        )
    )

    session = LiveSessionManager(
        websocket=mock_ws,
        initial_code="line 1\n",
        worker=mock_worker,
    )
    session.conductor = mock_conductor

    await session.on_dispatch_task("make ball transparent", "")
    await asyncio.gather(*list(session.active_worker_tasks))

    # Must NOT call notify_task_completed
    mock_conductor.notify_task_completed.assert_not_called()

    # Must call notify_task_failed with instruction and reason
    mock_conductor.notify_task_failed.assert_called_once_with(
        "make ball transparent", "Could not parse requested change"
    )

    # Must send StatusEvent notifying failure
    sent_msgs = [json.loads(c[0][0]) for c in mock_ws.send_text.call_args_list]
    status_msgs = [m for m in sent_msgs if m.get("type") == "status"]
    assert any("Edit failed" in m.get("message", "") for m in status_msgs)

