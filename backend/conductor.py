import asyncio
import base64
import logging
import os
from collections.abc import Awaitable, Callable

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
logger = logging.getLogger(__name__)

CONDUCTOR_SYSTEM_INSTRUCTION = """You are Gemini: Player 2, an interactive real-time AI pair programmer and game designer playing and hacking on a live 2D arcade physics game together with the user.

Key Persona & Style:
- You are sitting right beside the user as their gaming and coding co-pilot (Player 2).
- Talk in normal, natural, enthusiastic conversation via real-time voice.
- Keep spoken replies concise, natural, and punchy (1-3 sentences)—never lecture or monologue.
- Speak naturally without canned phrases or robotic scripts.

Capabilities & Tools:
1. `move_cursor(line, col, gesture)`: Move your collaborative Player 2 cursor to point to, highlight, or type at specific lines in the game editor to draw attention to code.
2. `inspect_code(start_line, end_line)`: Inspect the active code in the editor when you want to see what is on specific lines.
3. `dispatch_code_task(instruction, context_snippet)`: When the user asks to modify the game (physics, speed, colors, scoring, controls, visuals, new mechanics, powerups, bug fixes), invoke this tool with a clear instruction. Your background Antigravity worker will apply surgical edits to the code.
4. `react_emotion(mood, effect)`: Trigger visual game reactions and screen effects (e.g. mood='excited', effect='confetti', mood='celebrating', effect='pulse', mood='thinking', effect='nod').

When a code modification completes in the background, you will receive a realtime notification event. Acknowledge what was changed naturally as part of the live conversation."""


class LiveConductor:
    """The single, unified Conductor powered by Gemini Live API (gemini-3.8-live)

    for natural, real-time voice dialogue, multi-cursor coordination, and tool calling.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        voice_name: str | None = None,
        initial_code: str = "",
        on_audio_out: Callable[[bytes], Awaitable[None]] | None = None,
        on_transcript: Callable[[str, str], Awaitable[None]] | None = None,
        on_interrupted: Callable[[], Awaitable[None]] | None = None,
        on_cursor_move: Callable[[int, int, str], Awaitable[None]] | None = None,
        on_dispatch_task: Callable[[str, str], Awaitable[None]] | None = None,
        on_reaction: Callable[[str, str], Awaitable[None]] | None = None,
        on_status: Callable[[str, str | None], Awaitable[None]] | None = None,
    ):
        self.api_key = (
            api_key or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
        )
        self.model = model or os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")
        self.voice_name = voice_name or os.getenv("GEMINI_VOICE_NAME", "Puck")
        self.current_code = initial_code
        self.client: genai.Client | None = None
        self.session = None
        self.session_context = None
        self.session_resumption_handle: str | None = None
        self.is_running = False
        self.is_live = False
        self._pending_text: list[str] = []
        self._pending_notifications: list[str] = []

        # Callbacks
        self.on_audio_out = on_audio_out
        self.on_transcript = on_transcript
        self.on_interrupted = on_interrupted
        self.on_cursor_move = on_cursor_move
        self.on_dispatch_task = on_dispatch_task
        self.on_reaction = on_reaction
        self.on_status = on_status

    def update_code(self, code: str):
        """Updates the local mirror of the active codebase."""
        self.current_code = code

    def _build_tools(self) -> list[Callable]:
        """Defines the tools available to gemini-3.8-live."""

        def move_cursor(line: int, col: int, gesture: str = "hover") -> str:
            """Move your Player 2 cursor to line and col in the code editor with a gesture (e.g. 'hover', 'highlight', 'pointing', 'typing')."""
            return f"Cursor moved to {line}:{col}"

        def inspect_code(start_line: int = 1, end_line: int = 50) -> str:
            """Inspect lines of code currently active in the user's Monaco editor."""
            lines = self.current_code.splitlines()
            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), max(start_idx + 1, end_line))
            selected = lines[start_idx:end_idx]
            numbered = [
                f"{start_idx + i + 1}: {line_text}"
                for i, line_text in enumerate(selected)
            ]
            return "\n".join(numbered) or "No code available in range"

        def dispatch_code_task(instruction: str, context_snippet: str = "") -> str:
            """Dispatch a coding or gameplay modification task to your Antigravity background worker engine."""
            return f"Dispatched task: {instruction}"

        def react_emotion(mood: str, effect: str = "confetti") -> str:
            """React with an emotion and visual screen effect (e.g. mood='excited'/'celebrating', effect='confetti'/'nod'/'wiggle')."""
            return f"Reacted with {mood} ({effect})"

        return [move_cursor, inspect_code, dispatch_code_task, react_emotion]

    def _build_config(self) -> types.LiveConnectConfig:
        """Constructs the LiveConnectConfig for the Gemini Live API session."""
        tools = self._build_tools()
        session_resumption = (
            types.SessionResumptionConfig(handle=self.session_resumption_handle)
            if self.session_resumption_handle
            else types.SessionResumptionConfig()
        )
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice_name
                    )
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part.from_text(text=CONDUCTOR_SYSTEM_INSTRUCTION)]
            ),
            tools=tools,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            session_resumption=session_resumption,
        )

    async def _flush_pending_inputs(self):
        """Flushes any text inputs or notifications queued during transient reconnection windows."""
        if not self.session:
            return

        while self._pending_text:
            text = self._pending_text.pop(0)
            try:
                await self.session.send_realtime_input(text=text)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Error flushing queued text to Live API: {e}")
                self._pending_text.insert(0, text)
                break

        while self._pending_notifications:
            notif = self._pending_notifications.pop(0)
            try:
                await self.session.send_realtime_input(text=notif)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Error flushing queued notification to Live API: {e}")
                self._pending_notifications.insert(0, notif)
                break

    async def connect(self) -> bool:
        """Connects to the Gemini Multimodal Live API (gemini-3.8-live)."""
        self.is_running = True
        try:
            if not self.client:
                self.client = genai.Client(api_key=self.api_key)
            config = self._build_config()

            if self.session_resumption_handle:
                logger.info(
                    f"Resuming Gemini Live session with handle {self.session_resumption_handle} ({self.model}, voice: {self.voice_name})..."
                )
            else:
                logger.info(
                    f"Connecting to Gemini Live API ({self.model}, voice: {self.voice_name})..."
                )
            self.session_context = self.client.aio.live.connect(
                model=self.model,
                config=config,
            )
            self.session = await self.session_context.__aenter__()
            self.is_live = True
            logger.info("Connected to native Gemini Live API session successfully!")
            await self._flush_pending_inputs()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not establish Gemini Live connection ({e}).")
            self.is_live = False
            self.session = None
            return False

    async def notify_task_completed(
        self, summary: str, edited_lines: list[int] | None = None
    ):
        """Notifies the Live Model when an Antigravity worker task completes so it speaks naturally about it."""
        if not self.is_running:
            return

        line_info = f" on line(s) {edited_lines}" if edited_lines else ""
        event_text = f"[Environment update: Antigravity worker finished applying code changes{line_info}: {summary}]"

        if not self.session:
            self._pending_notifications.append(event_text)
            return

        try:
            await self.session.send_realtime_input(text=event_text)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Error notifying Live session of completion: {e}")
            self._pending_notifications.append(event_text)

    async def send_audio_chunk(self, pcm_16k_data: bytes):
        """Streams a 16kHz PCM audio chunk from the user's mic to gemini-3.8-live."""
        if not self.is_running or not self.session or not pcm_16k_data:
            return

        try:
            await self.session.send_realtime_input(
                audio=types.Blob(data=pcm_16k_data, mime_type="audio/pcm;rate=16000")
            )
        except Exception as e:  # noqa: BLE001
            if not self.is_live or not self.is_running or "1000" in str(e):
                logger.debug(f"Audio chunk dropped during session close/reconnect: {e}")
            else:
                logger.warning(f"Error sending audio chunk to Live API: {e}")

    async def send_audio_stream_end(self):
        """Flushes cached audio when the user pauses speaking or mutes microphone."""
        if not self.is_running or not self.session:
            return

        try:
            await self.session.send_realtime_input(audio_stream_end=True)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Error sending audio_stream_end: {e}")

    async def send_text(self, text: str):
        """Sends real-time user text input to gemini-3.8-live."""
        if not self.is_running or not text:
            return

        if not self.session:
            self._pending_text.append(text)
            return

        try:
            await self.session.send_realtime_input(text=text)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Error sending text to Live API: {e}")
            self._pending_text.append(text)

    async def listen_loop(
        self,
        max_retries: int = 5,
        initial_backoff: float = 1.0,
        max_backoff: float = 10.0,
    ):
        """Listens to server events from Gemini Live API with automatic reconnect and session resumption."""
        backoff = initial_backoff
        retries = 0

        while self.is_running:
            if not self.session:
                retries += 1
                if retries > max_retries:
                    logger.error("Max reconnect attempts reached for Gemini Live.")
                    if self.on_status:
                        await self.on_status(
                            "idle",
                            "Gemini Live disconnected (max retries reached)",
                        )
                    break

                if self.on_status:
                    await self.on_status(
                        "reconnecting",
                        f"Reconnecting to Gemini Live (attempt {retries})...",
                    )

                # If reconnecting with a cached resumption handle repeatedly fails, fall back to a fresh session
                if retries > 2 and self.session_resumption_handle:
                    logger.warning(
                        "Session resumption failed repeatedly; falling back to clean session."
                    )
                    self.session_resumption_handle = None

                connected = await self.connect()
                if not connected:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)
                    continue
                else:
                    backoff = initial_backoff
                    retries = 0
                    if self.on_status:
                        await self.on_status(
                            "listening",
                            "Connected: Gemini 3.8 Live (Voice & Multi-Cursor)",
                        )

            try:
                while self.is_running and self.session:
                    received_in_turn = 0
                    async for response in self.session.receive():
                        if not self.is_running:
                            break
                        received_in_turn += 1

                        backoff = initial_backoff
                        retries = 0

                        server_content = getattr(response, "server_content", None)
                        tool_call = getattr(response, "tool_call", None)
                        resumption = getattr(
                            response, "session_resumption_update", None
                        )
                        if resumption:
                            new_h = getattr(resumption, "new_handle", None)
                            if new_h is None and isinstance(resumption, dict):
                                new_h = resumption.get("new_handle")
                            if new_h:
                                self.session_resumption_handle = str(new_h)
                                logger.info(
                                    f"Updated session resumption handle: {self.session_resumption_handle}"
                                )

                        # 1. Handle Server Content (Interruption, Transcriptions, Audio Stream)
                        if server_content:
                            if getattr(server_content, "interrupted", False):
                                logger.info("Gemini Live interrupted by user barge-in!")
                                if self.on_interrupted:
                                    await self.on_interrupted()

                            # Transcriptions
                            input_tx = getattr(
                                server_content, "input_audio_transcription", None
                            )
                            if (
                                input_tx
                                and getattr(input_tx, "text", None)
                                and self.on_transcript
                            ):
                                await self.on_transcript("user", input_tx.text)

                            output_tx = getattr(
                                server_content, "output_audio_transcription", None
                            )
                            if (
                                output_tx
                                and getattr(output_tx, "text", None)
                                and self.on_transcript
                            ):
                                await self.on_transcript("gemini", output_tx.text)

                            # Model audio output (24kHz Linear PCM)
                            model_turn = getattr(server_content, "model_turn", None)
                            if model_turn and getattr(model_turn, "parts", None):
                                for part in model_turn.parts:
                                    inline_data = getattr(part, "inline_data", None)
                                    if inline_data and getattr(
                                        inline_data, "data", None
                                    ):
                                        raw_bytes = inline_data.data
                                        if isinstance(raw_bytes, str):
                                            raw_bytes = base64.b64decode(raw_bytes)
                                        if self.on_audio_out:
                                            await self.on_audio_out(raw_bytes)

                        # 2. Handle Tool Calls
                        if tool_call and getattr(tool_call, "function_calls", None):
                            function_responses = []
                            for call in tool_call.function_calls:
                                name = call.name
                                call_id = call.id or f"call_{name}"
                                args = call.args or {}
                                logger.info(
                                    f"Conductor received tool call: {name}({args})"
                                )

                                result_val = "ok"
                                try:
                                    if name == "move_cursor":
                                        raw_line = args.get("line")
                                        line = (
                                            int(raw_line) if raw_line is not None else 1
                                        )
                                        raw_col = args.get("col")
                                        col = int(raw_col) if raw_col is not None else 1
                                        gesture = str(args.get("gesture") or "hover")
                                        if self.on_cursor_move:
                                            await self.on_cursor_move(
                                                line, col, gesture
                                            )
                                        result_val = f"Moved cursor to {line}:{col}"

                                    elif name == "inspect_code":
                                        raw_start = args.get("start_line")
                                        start_l = (
                                            int(raw_start)
                                            if raw_start is not None
                                            else 1
                                        )
                                        raw_end = args.get("end_line")
                                        end_l = (
                                            int(raw_end) if raw_end is not None else 50
                                        )
                                        if self.on_cursor_move:
                                            await self.on_cursor_move(
                                                start_l, 1, "pointing"
                                            )
                                        lines = self.current_code.splitlines()
                                        start_idx = max(0, start_l - 1)
                                        end_idx = min(
                                            len(lines), max(start_idx + 1, end_l)
                                        )
                                        selected = lines[start_idx:end_idx]
                                        numbered = [
                                            f"{start_idx + i + 1}: {l_text}"
                                            for i, l_text in enumerate(selected)
                                        ]
                                        result_val = (
                                            "\n".join(numbered)
                                            or "No code available in range"
                                        )

                                    elif name == "dispatch_code_task":
                                        instruction = str(args.get("instruction") or "")
                                        context_snippet = str(
                                            args.get("context_snippet") or ""
                                        )
                                        if self.on_dispatch_task:
                                            await self.on_dispatch_task(
                                                instruction, context_snippet
                                            )
                                        result_val = f"Started task in Antigravity worker: {instruction}"

                                    elif name == "react_emotion":
                                        mood = str(args.get("mood") or "excited")
                                        effect = str(args.get("effect") or "confetti")
                                        if self.on_reaction:
                                            await self.on_reaction(mood, effect)
                                        result_val = f"Triggered {mood} with {effect}"
                                    else:
                                        result_val = f"Unknown tool: {name}"
                                except Exception as err:  # noqa: BLE001
                                    logger.error(
                                        f"Error executing tool '{name}': {err}"
                                    )
                                    result_val = f"Error executing tool '{name}': {err}"

                                function_responses.append(
                                    types.FunctionResponse(
                                        name=name,
                                        id=call_id,
                                        response={"result": result_val},
                                    )
                                )

                            # Return tool response to Gemini Live so it continues conversation naturally
                            if function_responses and self.session:
                                await self.session.send_tool_response(
                                    function_responses=function_responses
                                )

                    if not self.is_running:
                        break

                    if received_in_turn == 0:
                        logger.warning(
                            "Gemini Live session receive() returned 0 messages; session stream ended. Reconnecting..."
                        )
                        break

            except asyncio.CancelledError:
                logger.info("LiveConductor listen_loop cancelled.")
                break
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"Gemini Live stream interrupted ({e}). Preparing reconnect..."
                )
            finally:
                if self.session_context:
                    try:
                        await self.session_context.__aexit__(None, None, None)
                    except Exception as e:  # noqa: BLE001
                        logger.debug(f"Error exiting previous session_context: {e}")
                self.session = None
                self.is_live = False

        self.is_running = False
        self.is_live = False

    async def close(self):
        """Closes the Gemini Live session."""
        self.is_running = False
        self.is_live = False
        self._pending_text.clear()
        self._pending_notifications.clear()
        if hasattr(self, "session_context") and self.session_context:
            try:
                await self.session_context.__aexit__(None, None, None)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Error closing session: {e}")
        self.session = None
        self.session_context = None
