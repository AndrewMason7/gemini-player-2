"""Client WebSocket session lifecycle and event dispatching manager."""

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from backend.conductor import LiveConductor
from backend.constants import DEFAULT_BREAKOUT_CODE
from backend.models import (
    CursorMoveEvent,
    DiffChunk,
    EmotionEvent,
    InterruptedEvent,
    PingEvent,
    PongEvent,
    StatusEvent,
    ThoughtStreamEvent,
    TranscriptEvent,
)
from backend.worker import AntigravityWorker

__all__ = [
    "LiveSessionManager",
    "apply_code_edits",
    "handle_live_session",
]

logger = logging.getLogger("hellogemini.session")


def apply_code_edits(current_code: str, edits: list[DiffChunk]) -> str:
    """Apply surgical line edits (1-indexed) in reverse order to code."""
    if not edits:
        return current_code
    had_trailing_newline = current_code.endswith("\n")
    lines = current_code.splitlines()
    sorted_edits = sorted(edits, key=lambda e: e.start_line, reverse=True)
    for edit in sorted_edits:
        start_idx = max(0, edit.start_line - 1)
        normalized_end = max(edit.start_line, edit.end_line)
        end_idx = min(len(lines), normalized_end)
        rep_lines = edit.new_text.splitlines()
        lines[start_idx:end_idx] = rep_lines
    result = "\n".join(lines)
    if had_trailing_newline and not result.endswith("\n"):
        result += "\n"
    return result


class LiveSessionManager:
    """Manages an active client WebSocket connection, bridging the browser

    client to the LiveConductor and Antigravity background worker.
    """

    def __init__(
        self,
        websocket: WebSocket,
        initial_code: str = DEFAULT_BREAKOUT_CODE,
        conductor_cls: type[LiveConductor] | Any = None,
        worker: AntigravityWorker | None = None,
    ):
        self.websocket = websocket
        self.current_code = initial_code
        self.conductor_cls = conductor_cls or LiveConductor
        self.worker = worker or AntigravityWorker()
        self.conductor: LiveConductor | None = None
        self.listen_task: asyncio.Task | None = None
        self.active_worker_tasks: set[asyncio.Task] = set()
        self._send_lock = asyncio.Lock()
        self._worker_lock = asyncio.Lock()

    async def send_json_safe(self, data: dict[str, Any]) -> None:
        """Safely send a JSON payload to the client over WebSocket."""
        try:
            async with self._send_lock:
                await self.websocket.send_text(json.dumps(data))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Error sending json over ws: {e}")

    async def on_audio_out(self, pcm_24k_bytes: bytes) -> None:
        """Send synthesized audio PCM bytes from Conductor to client."""
        try:
            async with self._send_lock:
                await self.websocket.send_bytes(pcm_24k_bytes)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Error sending audio bytes over ws: {e}")

    async def on_transcript(self, sender: str, text: str) -> None:
        """Forward real-time dialogue transcripts to client."""
        evt = TranscriptEvent(sender=sender, text=text)
        await self.send_json_safe(evt.model_dump())

    async def on_interrupted(self) -> None:
        """Forward speech interruption event to client."""
        evt = InterruptedEvent()
        await self.send_json_safe(evt.model_dump())

    async def on_cursor_move(self, line: int, col: int, gesture: str) -> None:
        """Forward Player 2 cursor movement event to client."""
        evt = CursorMoveEvent(line=line, ch=col, gesture=gesture)
        await self.send_json_safe(evt.model_dump())

    async def on_reaction(self, mood: str, effect: str) -> None:
        """Forward emotion/visual reaction event to client."""
        evt = EmotionEvent(mood=mood, effect=effect)
        await self.send_json_safe(evt.model_dump())

    async def on_status(self, state: str, message: str | None = None) -> None:
        """Forward status state updates to client."""
        evt = StatusEvent(state=state, message=message)
        await self.send_json_safe(evt.model_dump())

    async def on_dispatch_task(self, instruction: str, context_snippet: str) -> None:
        """Execute a code modification task dispatched by the Conductor asynchronously."""
        logger.info(f"Conductor dispatched task: '{instruction}' to Antigravity worker")
        await self.send_json_safe(
            StatusEvent(state="coding", message=f"Coding: {instruction}").model_dump()
        )

        async def stream_thought(thought_chunk: str):
            evt = ThoughtStreamEvent(text=thought_chunk)
            await self.send_json_safe(evt.model_dump())

        async def run_worker():
            async with self._worker_lock:
                await self.send_json_safe(
                    StatusEvent(
                        state="coding", message=f"Coding: {instruction}"
                    ).model_dump()
                )
                try:
                    diff_result = await self.worker.execute_task(
                        instruction=instruction,
                        current_code=self.current_code,
                        on_thought=stream_thought,
                    )
                    # Apply edits to backend code mirror immediately
                    if diff_result.edits:
                        self.current_code = apply_code_edits(
                            self.current_code, diff_result.edits
                        )
                        if self.conductor:
                            self.conductor.update_code(self.current_code)
                        # Fly Player 2 cursor to the edited line with typing gesture
                        first_line = diff_result.edits[0].start_line
                        await self.on_cursor_move(first_line, 1, "typing")

                    # Push diff event to client
                    await self.send_json_safe(diff_result.model_dump())
                    await self.send_json_safe(
                        StatusEvent(state="listening", message="Ready").model_dump()
                    )

                    # Closed-loop notification back to Conductor
                    if self.conductor:
                        edited_lines = [e.start_line for e in diff_result.edits]
                        await self.conductor.notify_task_completed(
                            diff_result.description, edited_lines
                        )
                except asyncio.CancelledError:
                    logger.info(f"Worker task cancelled: '{instruction}'")
                    raise
                except Exception as e:
                    logger.exception(f"Error executing worker task '{instruction}'")
                    await self.send_json_safe(
                        StatusEvent(
                            state="listening",
                            message=f"Task error: {e}",
                        ).model_dump()
                    )

        worker_task = asyncio.create_task(run_worker())
        self.active_worker_tasks.add(worker_task)
        worker_task.add_done_callback(self.active_worker_tasks.discard)

    async def start_conductor(self) -> None:
        """Instantiate and connect the Conductor instance."""
        try:
            conductor_factory = self.conductor_cls or LiveConductor
            self.conductor = conductor_factory(
                initial_code=self.current_code,
                on_audio_out=self.on_audio_out,
                on_transcript=self.on_transcript,
                on_interrupted=self.on_interrupted,
                on_cursor_move=self.on_cursor_move,
                on_dispatch_task=self.on_dispatch_task,
                on_reaction=self.on_reaction,
                on_status=self.on_status,
            )
            is_live = await self.conductor.connect()
            if is_live:
                self.listen_task = asyncio.create_task(self.conductor.listen_loop())
                await self.send_json_safe(
                    StatusEvent(
                        state="listening",
                        message="Connected: Gemini 3.8 Live (Voice & Multi-Cursor)",
                    ).model_dump()
                )
            else:
                await self.send_json_safe(
                    StatusEvent(
                        state="idle",
                        message="Gemini 3.8 Live Offline (Check GEMINI_API_KEY)",
                    ).model_dump()
                )
        except Exception:
            logger.exception("Failed to connect LiveConductor")
            await self.send_json_safe(
                StatusEvent(
                    state="idle",
                    message="Gemini 3.8 Live Connection Error",
                ).model_dump()
            )

    async def handle_client_message(self, message: dict[str, Any]) -> None:
        """Process incoming raw WebSocket frame (binary audio or JSON text)."""
        if message.get("bytes"):
            # 16kHz PCM audio chunk from microphone
            raw_pcm = message["bytes"]
            if self.conductor and self.conductor.is_running:
                await self.conductor.send_audio_chunk(raw_pcm)

        elif message.get("text"):
            try:
                raw_text = message["text"].strip()
                if raw_text == "ping":
                    await self.send_json_safe(PongEvent().model_dump())
                    return

                payload = json.loads(raw_text)
                msg_type = payload.get("type")

                if msg_type == "ping":
                    ping_evt = PingEvent.model_validate(payload)
                    pong_evt = PongEvent(timestamp=ping_evt.timestamp)
                    await self.send_json_safe(pong_evt.model_dump())

                elif msg_type == "editor_sync":
                    new_code = payload.get("code")
                    if new_code is not None:
                        self.current_code = str(new_code)
                        if self.conductor:
                            self.conductor.update_code(self.current_code)

                elif msg_type == "text_input":
                    text = payload.get("text", "")
                    if self.conductor and self.conductor.is_running and text:
                        await self.conductor.send_text(text)

                elif msg_type == "audio_stream_end":
                    if self.conductor and self.conductor.is_running:
                        await self.conductor.send_audio_stream_end()

                elif (
                    msg_type == "user_interrupt"
                    and self.conductor
                    and self.conductor.is_running
                ):
                    await self.on_interrupted()

            except json.JSONDecodeError:
                pass

    async def receive_loop(self) -> None:
        """Continually receive messages from client until disconnect."""
        while True:
            message = await self.websocket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(code=message.get("code", 1000))
            await self.handle_client_message(message)

    async def close(self) -> None:
        """Cancel background tasks and clean up Conductor."""
        tasks_to_cancel = [t for t in self.active_worker_tasks if not t.done()]
        for t in tasks_to_cancel:
            t.cancel()
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        self.active_worker_tasks.clear()

        if self.listen_task:
            self.listen_task.cancel()
            try:
                await self.listen_task
            except asyncio.CancelledError:
                pass
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Error waiting for listen_task: {e}")
            self.listen_task = None

        if self.conductor:
            await self.conductor.close()

    async def handle(self) -> None:
        """Full lifecycle runner for a client WebSocket session."""
        await self.websocket.accept()
        logger.info("New client WebSocket connection accepted.")

        await self.start_conductor()

        try:
            await self.receive_loop()
        except (WebSocketDisconnect, RuntimeError):
            logger.info("Client WebSocket disconnected.")
        except Exception:
            logger.exception("WebSocket session error")
        finally:
            await self.close()


async def handle_live_session(
    websocket: WebSocket,
    initial_code: str = DEFAULT_BREAKOUT_CODE,
    conductor_cls: type[LiveConductor] | Any = None,
    worker: AntigravityWorker | None = None,
) -> None:
    """Convenience helper to create and run a LiveSessionManager."""
    session = LiveSessionManager(
        websocket=websocket,
        initial_code=initial_code,
        conductor_cls=conductor_cls,
        worker=worker,
    )
    await session.handle()
