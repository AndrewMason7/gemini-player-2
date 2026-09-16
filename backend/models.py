from typing import Literal

from pydantic import BaseModel


class CursorPosition(BaseModel):
    line: int
    ch: int
    file: str | None = "breakout.js"


class CursorMoveEvent(BaseModel):
    type: Literal["cursor_move"] = "cursor_move"
    line: int
    ch: int
    gesture: str | None = "hover"  # "hover", "highlight", "pointing", "typing"
    tag: str = "Gemini (Player 2)"


class ThoughtStreamEvent(BaseModel):
    type: Literal["thought_stream"] = "thought_stream"
    text: str
    stage: str | None = "reasoning"


class DiffChunk(BaseModel):
    start_line: int
    start_col: int = 1
    end_line: int
    end_col: int = 1
    new_text: str
    description: str | None = None


class CodeDiffEvent(BaseModel):
    type: Literal["code_diff"] = "code_diff"
    edits: list[DiffChunk]
    description: str
    modified_code: str | None = None


class EmotionEvent(BaseModel):
    type: Literal["reaction"] = "reaction"
    mood: str  # "excited", "celebrating", "thinking", "curious"
    effect: str  # "confetti", "nod", "wiggle", "pulse"


class TranscriptEvent(BaseModel):
    type: Literal["transcript"] = "transcript"
    sender: Literal["user", "gemini"]
    text: str
    is_final: bool = True


class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    state: Literal[
        "disconnected",
        "connecting",
        "reconnecting",
        "idle",
        "listening",
        "speaking",
        "coding",
    ]
    message: str | None = None


class InterruptedEvent(BaseModel):
    type: Literal["interrupted"] = "interrupted"


class PingEvent(BaseModel):
    type: Literal["ping"] = "ping"
    timestamp: float | int | None = None


class PongEvent(BaseModel):
    type: Literal["pong"] = "pong"
    timestamp: float | int | None = None


class ClientEditorSync(BaseModel):
    type: Literal["editor_sync"] = "editor_sync"
    code: str
    cursor: CursorPosition | None = None
