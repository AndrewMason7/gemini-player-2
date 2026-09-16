from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.conductor import LiveConductor
from backend.session import LiveSessionManager


@pytest.mark.anyio
async def test_conductor_mid_speech_drop_and_resumption(monkeypatch):
    """Verifies that when Gemini Live drops connection mid-speech (after emitting
    audio chunks), the conductor catches the drop, transitions to reconnecting,
    resumes using the session resumption handle, and continues audio streaming.
    """
    statuses = []
    received_audio = []

    async def on_status(state: str, message: str | None = None):
        statuses.append((state, message))

    async def on_audio_out(pcm_data: bytes):
        received_audio.append(pcm_data)

    conductor = LiveConductor(on_status=on_status, on_audio_out=on_audio_out)
    conductor.is_running = True

    # First session: streams 2 chunks of 24kHz audio, updates resumption handle, then drops mid-speech
    session1 = AsyncMock()

    chunk1_msg = MagicMock()
    chunk1_msg.tool_call = None
    chunk1_msg.session_resumption_update = MagicMock(
        new_handle="resume-handle-speech-123"
    )
    chunk1_part = MagicMock()
    chunk1_part.inline_data.data = b"\x01\x02\x03\x04"
    chunk1_msg.server_content.model_turn.parts = [chunk1_part]
    chunk1_msg.server_content.interrupted = False
    chunk1_msg.server_content.input_audio_transcription = None
    chunk1_msg.server_content.output_audio_transcription = None

    chunk2_msg = MagicMock()
    chunk2_msg.tool_call = None
    chunk2_msg.session_resumption_update = None
    chunk2_part = MagicMock()
    chunk2_part.inline_data.data = b"\x05\x06\x07\x08"
    chunk2_msg.server_content.model_turn.parts = [chunk2_part]
    chunk2_msg.server_content.interrupted = False
    chunk2_msg.server_content.input_audio_transcription = None
    chunk2_msg.server_content.output_audio_transcription = None

    async def receive_stream_broken():
        yield chunk1_msg
        yield chunk2_msg
        # Connection severed mid-speech
        raise ConnectionResetError("Socket reset mid-speech playback")

    session1.receive = receive_stream_broken

    # Second session: resumed session delivers remainder of speech
    session2 = AsyncMock()

    chunk3_msg = MagicMock()
    chunk3_msg.tool_call = None
    chunk3_msg.session_resumption_update = None
    chunk3_part = MagicMock()
    chunk3_part.inline_data.data = b"\x09\x0a\x0b\x0c"
    chunk3_msg.server_content.model_turn.parts = [chunk3_part]
    chunk3_msg.server_content.interrupted = False
    chunk3_msg.server_content.input_audio_transcription = None
    chunk3_msg.server_content.output_audio_transcription.text = "Finished speech."

    async def receive_resumed():
        yield chunk3_msg
        conductor.is_running = False

    session2.receive = receive_resumed

    sessions = [session1, session2]

    async def mock_connect():
        if sessions:
            conductor.session = sessions.pop(0)
            conductor.is_live = True
            return True
        return False

    monkeypatch.setattr(conductor, "connect", mock_connect)

    await conductor.listen_loop(max_retries=3, initial_backoff=0.01, max_backoff=0.05)

    # Audio from before and after disconnect was both received
    assert len(received_audio) == 3
    assert received_audio[0] == b"\x01\x02\x03\x04"
    assert received_audio[1] == b"\x05\x06\x07\x08"
    assert received_audio[2] == b"\x09\x0a\x0b\x0c"

    # Conductor preserved resumption handle across drop
    assert conductor.session_resumption_handle == "resume-handle-speech-123"

    # Status transitioned through reconnecting and back to listening
    states = [s[0] for s in statuses]
    assert "reconnecting" in states
    assert "listening" in states


@pytest.mark.anyio
async def test_session_manager_client_socket_drops_mid_audio():
    """Verifies that when client browser WebSocket abruptly drops during an active
    audio stream, LiveSessionManager catches the socket error safely without
    hanging or corrupting locks.
    """
    mock_ws = AsyncMock()
    # Simulate client websocket breaking mid-audio write
    mock_ws.send_bytes.side_effect = RuntimeError("WebSocket connection is closed")

    session = LiveSessionManager(websocket=mock_ws)

    # Sending audio chunks while socket is broken should be safely caught and not throw
    await session.on_audio_out(b"\x00\x01" * 100)
    assert mock_ws.send_bytes.call_count == 1

    # Ensure send lock was released and not held
    assert not session._send_lock.locked()


@pytest.mark.anyio
async def test_session_manager_reconnect_sync_flow():
    """Verifies that a reconnected client session syncs code and seamlessly
    hands off to a fresh conductor instance.
    """
    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()

    # Session 1: Client makes initial edits
    session1 = LiveSessionManager(
        websocket=mock_ws1,
        initial_code="// initial code",
    )
    await session1.handle_client_message(
        {"text": '{"type": "editor_sync", "code": "// updated code"}'}
    )
    assert session1.current_code == "// updated code"

    # Session 1 closes on client disconnect
    await session1.close()

    # Session 2: Client reconnects, passing last-known code
    mock_conductor = MagicMock()
    mock_conductor.update_code = MagicMock()
    mock_conductor.connect = AsyncMock(return_value=True)
    mock_conductor.is_running = True

    def conductor_factory(**kwargs):
        return mock_conductor

    session2 = LiveSessionManager(
        websocket=mock_ws2,
        initial_code=session1.current_code,
        conductor_cls=conductor_factory,
    )
    assert session2.current_code == "// updated code"

    await session2.start_conductor()
    mock_conductor.connect.assert_called_once()
