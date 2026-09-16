from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import types

from backend.conductor import CONDUCTOR_SYSTEM_INSTRUCTION, LiveConductor


@pytest.mark.anyio
async def test_conductor_initialization():
    conductor = LiveConductor(
        api_key="test-api-key",
        model="gemini-3.8-live",
        voice_name="Puck",
        initial_code="const a = 1;\nconst b = 2;",
    )
    assert conductor.api_key == "test-api-key"
    assert conductor.model == "gemini-3.8-live"
    assert conductor.voice_name == "Puck"
    assert conductor.current_code == "const a = 1;\nconst b = 2;"
    assert not conductor.is_live
    assert not conductor.is_running


@pytest.mark.anyio
async def test_conductor_tools_and_config():
    conductor = LiveConductor(
        initial_code="let speed = 5;\nlet score = 0;\nfunction update() {}\n",
    )
    tools = conductor._build_tools()
    assert len(tools) == 4
    tool_names = [t.__name__ for t in tools]
    assert "move_cursor" in tool_names
    assert "inspect_code" in tool_names
    assert "dispatch_code_task" in tool_names
    assert "react_emotion" in tool_names

    # Test inspect_code
    inspect_fn = next(t for t in tools if t.__name__ == "inspect_code")
    inspected = inspect_fn(1, 2)
    assert "1: let speed = 5;" in inspected
    assert "2: let score = 0;" in inspected

    # Test config
    config = conductor._build_config()
    assert config.response_modalities == [types.Modality.AUDIO]
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"
    assert CONDUCTOR_SYSTEM_INSTRUCTION in config.system_instruction.parts[0].text


@pytest.mark.anyio
async def test_conductor_connect_success(monkeypatch):
    conductor = LiveConductor(api_key="test-key")

    mock_session = AsyncMock()
    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_session)
    mock_context.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.aio.live.connect = MagicMock(return_value=mock_context)

    monkeypatch.setattr(
        "backend.conductor.genai.Client", MagicMock(return_value=mock_client)
    )

    connected = await conductor.connect()
    assert connected is True
    assert conductor.is_live is True
    assert conductor.is_running is True
    assert conductor.session == mock_session

    await conductor.close()
    assert conductor.is_running is False
    assert conductor.session is None


@pytest.mark.anyio
async def test_conductor_send_methods():
    conductor = LiveConductor(api_key="test-key")
    conductor.is_running = True
    conductor.is_live = True

    mock_session = AsyncMock()
    conductor.session = mock_session

    # 1. send_audio_chunk
    raw_pcm = b"\x00\x01" * 100
    await conductor.send_audio_chunk(raw_pcm)
    mock_session.send_realtime_input.assert_called_once()
    call_kwargs = mock_session.send_realtime_input.call_args.kwargs
    assert "audio" in call_kwargs
    assert call_kwargs["audio"].data == raw_pcm
    assert call_kwargs["audio"].mime_type == "audio/pcm;rate=16000"

    # 2. send_audio_stream_end
    mock_session.reset_mock()
    await conductor.send_audio_stream_end()
    mock_session.send_realtime_input.assert_called_once_with(audio_stream_end=True)

    # 3. send_text
    mock_session.reset_mock()
    await conductor.send_text("Make the paddle wider")
    mock_session.send_realtime_input.assert_called_once_with(
        text="Make the paddle wider"
    )

    # 4. notify_task_completed
    mock_session.reset_mock()
    await conductor.notify_task_completed(
        "Increased paddle width", edited_lines=[10, 11]
    )
    mock_session.send_realtime_input.assert_called_once_with(
        text="[Environment update: Antigravity worker finished applying code changes on line(s) [10, 11]: Increased paddle width]"
    )

    # 5. notify_task_failed
    mock_session.reset_mock()
    await conductor.notify_task_failed("Double ball speed", "Syntax error in edit")
    mock_session.send_realtime_input.assert_called_once()
    failed_text = mock_session.send_realtime_input.call_args[1]["text"]
    assert "FAILED to apply code changes" in failed_text
    assert "Double ball speed" in failed_text
    assert "Syntax error in edit" in failed_text


@pytest.mark.anyio
async def test_conductor_listen_loop():
    audio_chunks = []
    transcripts = []
    interruptions = []
    cursor_moves = []
    dispatched_tasks = []
    reactions = []

    async def on_audio_out(data: bytes):
        audio_chunks.append(data)

    async def on_transcript(sender: str, text: str):
        transcripts.append((sender, text))

    async def on_interrupted():
        interruptions.append(True)

    async def on_cursor_move(line: int, col: int, gesture: str):
        cursor_moves.append((line, col, gesture))

    async def on_dispatch_task(instruction: str, context: str):
        dispatched_tasks.append((instruction, context))

    async def on_reaction(mood: str, effect: str):
        reactions.append((mood, effect))

    conductor = LiveConductor(
        initial_code="console.log('test');",
        on_audio_out=on_audio_out,
        on_transcript=on_transcript,
        on_interrupted=on_interrupted,
        on_cursor_move=on_cursor_move,
        on_dispatch_task=on_dispatch_task,
        on_reaction=on_reaction,
    )
    conductor.is_running = True
    conductor.is_live = True

    # Response 1: Interruption, Transcriptions, Audio
    resp1 = MagicMock()
    resp1.tool_call = None
    resp1.session_resumption_update = MagicMock(new_handle="resume-handle-xyz")
    resp1.server_content.interrupted = True
    resp1.server_content.input_audio_transcription.text = "Hey Gemini"
    resp1.server_content.output_audio_transcription.text = "Hello! Ready to play!"
    part1 = MagicMock()
    part1.inline_data.data = b"\x12\x34\x56"
    resp1.server_content.model_turn.parts = [part1]

    # Response 2: Tool Calls
    resp2 = MagicMock()
    resp2.server_content = None
    resp2.session_resumption_update = None
    call_cursor = MagicMock()
    call_cursor.name = "move_cursor"
    call_cursor.id = "call_1"
    call_cursor.args = {"line": 12, "col": 3, "gesture": "highlight"}

    call_dispatch = MagicMock()
    call_dispatch.name = "dispatch_code_task"
    call_dispatch.id = "call_2"
    call_dispatch.args = {"instruction": "Double ball speed"}

    call_react = MagicMock()
    call_react.name = "react_emotion"
    call_react.id = "call_3"
    call_react.args = {"mood": "celebrating", "effect": "confetti"}

    call_inspect = MagicMock()
    call_inspect.name = "inspect_code"
    call_inspect.id = "call_4"
    call_inspect.args = {"start_line": 15, "end_line": 20}

    resp2.tool_call.function_calls = [
        call_cursor,
        call_dispatch,
        call_react,
        call_inspect,
    ]

    async def mock_receive_gen():
        yield resp1
        yield resp2
        conductor.is_running = False

    mock_session = AsyncMock()
    mock_session.receive = mock_receive_gen
    conductor.session = mock_session

    await conductor.listen_loop()

    # Assert callbacks triggered
    assert len(interruptions) == 1
    assert ("user", "Hey Gemini") in transcripts
    assert ("gemini", "Hello! Ready to play!") in transcripts
    assert b"\x12\x34\x56" in audio_chunks
    assert (12, 3, "highlight") in cursor_moves
    assert (15, 1, "pointing") in cursor_moves
    assert ("Double ball speed", "") in dispatched_tasks
    assert ("celebrating", "confetti") in reactions
    assert conductor.session_resumption_handle == "resume-handle-xyz"

    # Assert tool responses sent back
    mock_session.send_tool_response.assert_called_once()
    tool_resp_args = mock_session.send_tool_response.call_args.kwargs[
        "function_responses"
    ]
    assert len(tool_resp_args) == 4
    assert tool_resp_args[0].name == "move_cursor"
    assert tool_resp_args[1].name == "dispatch_code_task"
    assert tool_resp_args[2].name == "react_emotion"
    assert tool_resp_args[3].name == "inspect_code"


@pytest.mark.anyio
async def test_conductor_multi_turn_listen_loop():
    transcripts = []
    audio_chunks = []

    async def on_transcript(sender: str, text: str):
        transcripts.append((sender, text))

    async def on_audio_out(data: bytes):
        audio_chunks.append(data)

    conductor = LiveConductor(
        on_transcript=on_transcript,
        on_audio_out=on_audio_out,
    )
    conductor.is_running = True
    conductor.is_live = True

    # Turn 1: model yields output and turn completes (generator finishes)
    turn1_msg = MagicMock()
    turn1_msg.tool_call = None
    turn1_msg.session_resumption_update = None
    turn1_msg.server_content.interrupted = False
    turn1_msg.server_content.input_audio_transcription = None
    turn1_msg.server_content.output_audio_transcription.text = "Turn 1 reply"
    part1 = MagicMock()
    part1.inline_data.data = b"\xaa\xbb"
    turn1_msg.server_content.model_turn.parts = [part1]

    # Turn 2: next turn on the same persistent session
    turn2_msg = MagicMock()
    turn2_msg.tool_call = None
    turn2_msg.session_resumption_update = None
    turn2_msg.server_content.interrupted = False
    turn2_msg.server_content.input_audio_transcription = None
    turn2_msg.server_content.output_audio_transcription.text = "Turn 2 reply"
    part2 = MagicMock()
    part2.inline_data.data = b"\xcc\xdd"
    turn2_msg.server_content.model_turn.parts = [part2]

    turn_count = 0

    async def turn1_generator():
        yield turn1_msg
        # Turn 1 completes naturally; generator terminates

    async def turn2_generator():
        yield turn2_msg
        # Conductor stopped cleanly during/after turn 2
        conductor.is_running = False

    def receive_side_effect():
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            return turn1_generator()
        elif turn_count == 2:
            return turn2_generator()
        conductor.is_running = False

        async def empty_gen():
            if False:
                yield None

        return empty_gen()

    mock_session = AsyncMock()
    mock_session.receive = MagicMock(side_effect=receive_side_effect)
    conductor.session = mock_session

    mock_context = MagicMock()
    mock_context.__aexit__ = AsyncMock(return_value=None)
    conductor.session_context = mock_context

    await conductor.listen_loop()

    # Both turns were processed on the same persistent session
    assert len(transcripts) == 2
    assert ("gemini", "Turn 1 reply") in transcripts
    assert ("gemini", "Turn 2 reply") in transcripts
    assert b"\xaa\xbb" in audio_chunks
    assert b"\xcc\xdd" in audio_chunks

    # session.receive() was called for each turn separately
    assert turn_count == 2
    assert mock_session.receive.call_count == 2

    # session_context was not exited between turns; only exited once during listen_loop shutdown
    assert mock_context.__aexit__.call_count == 1


@pytest.mark.anyio
async def test_conductor_multi_turn_with_tool_call():
    """Verifies that after dispatching a tool call and returning the response,
    the persistent session survives turn_complete and continues receiving subsequent turns.
    """
    transcripts = []
    dispatched = []

    async def on_transcript(sender: str, text: str):
        transcripts.append((sender, text))

    async def on_dispatch_task(instruction: str, context: str):
        dispatched.append((instruction, context))

    conductor = LiveConductor(
        on_transcript=on_transcript,
        on_dispatch_task=on_dispatch_task,
    )
    conductor.is_running = True
    conductor.is_live = True

    # Turn 1: Model invokes dispatch_code_task tool call to change ball color
    turn1_msg = MagicMock()
    turn1_msg.server_content = None
    turn1_msg.session_resumption_update = None
    call_dispatch = MagicMock()
    call_dispatch.name = "dispatch_code_task"
    call_dispatch.id = "call_color_change"
    call_dispatch.args = {"instruction": "Change the ball color to red"}
    turn1_msg.tool_call.function_calls = [call_dispatch]

    # Turn 2: After tool response is sent and worker finishes, model speaks follow-up
    turn2_msg = MagicMock()
    turn2_msg.tool_call = None
    turn2_msg.session_resumption_update = None
    turn2_msg.server_content.interrupted = False
    turn2_msg.server_content.input_audio_transcription = None
    turn2_msg.server_content.output_audio_transcription.text = (
        "I've changed the ball color to red!"
    )
    turn2_msg.server_content.model_turn = None

    turn_count = 0

    async def turn1_generator():
        yield turn1_msg

    async def turn2_generator():
        yield turn2_msg
        conductor.is_running = False

    def receive_side_effect():
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            return turn1_generator()
        elif turn_count == 2:
            return turn2_generator()
        conductor.is_running = False

        async def empty_gen():
            if False:
                yield None

        return empty_gen()

    mock_session = AsyncMock()
    mock_session.receive = MagicMock(side_effect=receive_side_effect)
    conductor.session = mock_session

    mock_context = MagicMock()
    mock_context.__aexit__ = AsyncMock(return_value=None)
    conductor.session_context = mock_context

    await conductor.listen_loop()

    # Tool was dispatched
    assert dispatched == [("Change the ball color to red", "")]

    # Tool response was sent back upstream
    mock_session.send_tool_response.assert_called_once()
    call_kwargs = mock_session.send_tool_response.call_args.kwargs
    assert len(call_kwargs["function_responses"]) == 1
    assert call_kwargs["function_responses"][0].name == "dispatch_code_task"
    assert call_kwargs["function_responses"][0].id == "call_color_change"

    # Next turn speech was received on the same session
    assert ("gemini", "I've changed the ball color to red!") in transcripts

    # Two separate receive() turns on the same session
    assert turn_count == 2
    assert mock_session.receive.call_count == 2
    assert mock_context.__aexit__.call_count == 1


@pytest.mark.anyio
async def test_conductor_empty_generator_safeguard(monkeypatch):
    """Verifies that an empty generator (0 messages yielded) does not cause
    a busy-loop; instead it breaks out cleanly and triggers session reconnection.
    """
    statuses = []

    async def on_status(state: str, message: str | None = None):
        statuses.append((state, message))

    conductor = LiveConductor(on_status=on_status)
    conductor.is_running = True
    conductor.is_live = True

    # First session returns empty generator (0 messages)
    empty_session = AsyncMock()

    async def empty_gen():
        if False:
            yield None

    empty_session.receive = empty_gen

    # Second session receives a valid message and then shuts down conductor cleanly
    valid_session = AsyncMock()
    valid_msg = MagicMock()
    valid_msg.tool_call = None
    valid_msg.session_resumption_update = None
    valid_msg.server_content.interrupted = False
    valid_msg.server_content.input_audio_transcription = None
    valid_msg.server_content.output_audio_transcription.text = (
        "Recovered after empty stream"
    )
    valid_msg.server_content.model_turn = None

    async def valid_gen():
        yield valid_msg
        conductor.is_running = False

    valid_session.receive = valid_gen

    sessions = [empty_session, valid_session]

    async def mock_connect():
        if sessions:
            conductor.session = sessions.pop(0)
            conductor.is_live = True
            return True
        return False

    conductor.session = empty_session
    monkeypatch.setattr(conductor, "connect", mock_connect)

    await conductor.listen_loop(max_retries=3, initial_backoff=0.01, max_backoff=0.05)

    assert any(s[0] == "reconnecting" for s in statuses)
    assert any(s[0] == "listening" for s in statuses)


@pytest.mark.anyio
async def test_conductor_tool_call_resilience_on_error():
    """Verifies that tool call handler exceptions and malformed arguments
    do not crash the listen loop or tear down the live session context,
    but return error descriptions back to Gemini.
    """

    async def failing_dispatch(instruction: str, context: str):
        raise RuntimeError("Worker pool capacity reached")

    conductor = LiveConductor(on_dispatch_task=failing_dispatch)
    conductor.is_running = True
    conductor.is_live = True

    call_fail = MagicMock()
    call_fail.name = "dispatch_code_task"
    call_fail.id = "call_error"
    call_fail.args = {"instruction": "change ball color"}

    call_bad_args = MagicMock()
    call_bad_args.name = "move_cursor"
    call_bad_args.id = "call_bad_cursor"
    call_bad_args.args = {"line": None, "col": "not_an_int"}

    msg = MagicMock()
    msg.server_content = None
    msg.session_resumption_update = None
    msg.tool_call.function_calls = [call_fail, call_bad_args]

    async def single_turn_gen():
        yield msg
        conductor.is_running = False

    mock_session = AsyncMock()
    mock_session.receive = single_turn_gen
    conductor.session = mock_session

    mock_context = MagicMock()
    mock_context.__aexit__ = AsyncMock(return_value=None)
    conductor.session_context = mock_context

    await conductor.listen_loop()

    mock_session.send_tool_response.assert_called_once()
    responses = mock_session.send_tool_response.call_args.kwargs["function_responses"]
    assert len(responses) == 2
    assert "Worker pool capacity reached" in responses[0].response["result"]
    assert "Error executing tool 'move_cursor'" in responses[1].response["result"]

    # Session context is preserved and only exited on conductor shutdown
    assert mock_context.__aexit__.call_count == 1


@pytest.mark.anyio
async def test_conductor_multi_turn_interrupted_barge_in():
    """Verifies that user barge-in (interrupted=True) during multi-turn operation
    calls on_interrupted callback while keeping the persistent session alive across turns.
    """
    interrupted_calls = []
    transcripts = []

    async def on_interrupted():
        interrupted_calls.append(True)

    async def on_transcript(sender: str, text: str):
        transcripts.append((sender, text))

    conductor = LiveConductor(
        on_interrupted=on_interrupted,
        on_transcript=on_transcript,
    )
    conductor.is_running = True
    conductor.is_live = True

    # Turn 1: model output is cut off by user barge-in
    turn1_msg = MagicMock()
    turn1_msg.tool_call = None
    turn1_msg.session_resumption_update = None
    turn1_msg.server_content.interrupted = True
    turn1_msg.server_content.input_audio_transcription = None
    turn1_msg.server_content.output_audio_transcription.text = "I am startin..."
    turn1_msg.server_content.model_turn = None

    # Turn 2: next turn yields new response after interruption
    turn2_msg = MagicMock()
    turn2_msg.tool_call = None
    turn2_msg.session_resumption_update = None
    turn2_msg.server_content.interrupted = False
    turn2_msg.server_content.input_audio_transcription = None
    turn2_msg.server_content.output_audio_transcription.text = (
        "Understood, changing directions."
    )
    turn2_msg.server_content.model_turn = None

    turn_count = 0

    async def turn1_gen():
        yield turn1_msg

    async def turn2_gen():
        yield turn2_msg
        conductor.is_running = False

    def receive_side_effect():
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            return turn1_gen()
        return turn2_gen()

    mock_session = AsyncMock()
    mock_session.receive = MagicMock(side_effect=receive_side_effect)
    conductor.session = mock_session

    mock_context = MagicMock()
    mock_context.__aexit__ = AsyncMock(return_value=None)
    conductor.session_context = mock_context

    await conductor.listen_loop()

    assert len(interrupted_calls) == 1
    assert ("gemini", "I am startin...") in transcripts
    assert ("gemini", "Understood, changing directions.") in transcripts
    assert mock_session.receive.call_count == 2
    assert mock_context.__aexit__.call_count == 1


@pytest.mark.anyio
async def test_conductor_session_resumption_config():
    # 1. No resumption handle initially -> empty session_resumption
    conductor = LiveConductor()
    config1 = conductor._build_config()
    assert config1.session_resumption is not None
    assert config1.session_resumption.handle is None

    # 2. Resumption handle present -> session_resumption includes handle
    conductor.session_resumption_handle = "previous-handle-12345"
    config2 = conductor._build_config()
    assert config2.session_resumption.handle == "previous-handle-12345"


@pytest.mark.anyio
async def test_conductor_upstream_reconnection(monkeypatch):
    statuses = []

    async def on_status(state: str, message: str | None = None):
        statuses.append((state, message))

    conductor = LiveConductor(on_status=on_status)
    conductor.is_running = True

    # First session drops with an error after 1 message
    session1 = AsyncMock()
    msg1 = MagicMock()
    msg1.tool_call = None
    msg1.session_resumption_update = MagicMock(new_handle="resume-token-abc")
    msg1.server_content = None

    async def receive1():
        yield msg1
        raise ConnectionResetError("Stream abruptly disconnected")

    session1.receive = receive1

    # Second session receives final message and terminates cleanly
    session2 = AsyncMock()
    msg2 = MagicMock()
    msg2.tool_call = None
    msg2.session_resumption_update = None
    msg2.server_content.output_audio_transcription.text = "Resumed successfully!"
    msg2.server_content.input_audio_transcription = None
    msg2.server_content.model_turn = None
    msg2.server_content.interrupted = False

    async def receive2():
        yield msg2
        conductor.is_running = False

    session2.receive = receive2

    sessions = [session1, session2]

    async def mock_connect():
        if sessions:
            conductor.session = sessions.pop(0)
            conductor.is_live = True
            return True
        return False

    monkeypatch.setattr(conductor, "connect", mock_connect)

    # Run listen loop with tiny initial backoff for quick test
    await conductor.listen_loop(max_retries=3, initial_backoff=0.01, max_backoff=0.05)

    assert conductor.session_resumption_handle == "resume-token-abc"
    assert any(s[0] == "reconnecting" for s in statuses)
    assert any(s[0] == "listening" for s in statuses)


@pytest.mark.anyio
async def test_conductor_pending_queues_and_flush():
    conductor = LiveConductor()
    conductor.is_running = True
    conductor.session = None  # Reconnecting state

    # Queue text and notification while session is down
    await conductor.send_text("Queued prompt 1")
    await conductor.notify_task_completed("Applied changes", edited_lines=[5])

    assert len(conductor._pending_text) == 1
    assert conductor._pending_text[0] == "Queued prompt 1"
    assert len(conductor._pending_notifications) == 1

    # Mock session connected
    mock_session = AsyncMock()
    conductor.session = mock_session

    await conductor._flush_pending_inputs()

    assert len(conductor._pending_text) == 0
    assert len(conductor._pending_notifications) == 0
    assert mock_session.send_realtime_input.call_count == 2


@pytest.mark.anyio
async def test_conductor_resumption_fallback_on_repeated_failure(monkeypatch):
    statuses = []

    async def on_status(state: str, message: str | None = None):
        statuses.append((state, message))

    conductor = LiveConductor(on_status=on_status)
    conductor.session_resumption_handle = "stale-expired-handle"
    conductor.is_running = True

    connect_attempts = 0

    async def mock_connect():
        nonlocal connect_attempts
        connect_attempts += 1
        # Fails on attempts 1 and 2 with stale handle, succeeds on attempt 3 after handle is cleared
        if conductor.session_resumption_handle is not None:
            return False
        # Clean session succeeds
        mock_sess = AsyncMock()

        async def empty_recv():
            conductor.is_running = False
            if False:
                yield None

        mock_sess.receive = empty_recv
        conductor.session = mock_sess
        conductor.is_live = True
        return True

    monkeypatch.setattr(conductor, "connect", mock_connect)

    await conductor.listen_loop(max_retries=5, initial_backoff=0.01, max_backoff=0.02)

    assert conductor.session_resumption_handle is None
    assert connect_attempts >= 3
    assert any(s[0] == "listening" for s in statuses)


@pytest.mark.anyio
async def test_conductor_max_retries_exceeded(monkeypatch):
    statuses = []

    async def on_status(state: str, message: str | None = None):
        statuses.append((state, message))

    conductor = LiveConductor(on_status=on_status)
    conductor.is_running = True

    async def mock_connect():
        return False

    monkeypatch.setattr(conductor, "connect", mock_connect)

    await conductor.listen_loop(max_retries=2, initial_backoff=0.01, max_backoff=0.02)

    assert not conductor.is_running
    assert statuses[-1][0] == "idle"
    assert "max retries reached" in statuses[-1][1]
