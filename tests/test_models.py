from backend.models import (
    ClientEditorSync,
    CodeDiffEvent,
    CursorMoveEvent,
    DiffChunk,
    EmotionEvent,
    InterruptedEvent,
    StatusEvent,
    ThoughtStreamEvent,
    TranscriptEvent,
)


def test_cursor_move_event():
    evt = CursorMoveEvent(line=15, ch=4, gesture="highlight")
    data = evt.model_dump()
    assert data["type"] == "cursor_move"
    assert data["line"] == 15
    assert data["ch"] == 4
    assert data["tag"] == "Gemini (Player 2)"


def test_code_diff_event():
    chunk = DiffChunk(
        start_line=10,
        start_col=1,
        end_line=12,
        end_col=1,
        new_text="paddle.speed = 15;\n",
        description="Boost paddle speed",
    )
    diff_evt = CodeDiffEvent(
        edits=[chunk],
        description="Applied paddle boost",
    )
    data = diff_evt.model_dump()
    assert data["type"] == "code_diff"
    assert len(data["edits"]) == 1
    assert data["edits"][0]["start_line"] == 10


def test_thought_stream_event():
    thought = ThoughtStreamEvent(text="Evaluating canvas physics bounds...")
    data = thought.model_dump()
    assert data["type"] == "thought_stream"
    assert "physics" in data["text"]


def test_interrupted_event():
    evt = InterruptedEvent()
    assert evt.type == "interrupted"


def test_editor_sync():
    sync = ClientEditorSync(code="console.log('hi');")
    assert sync.type == "editor_sync"
    assert sync.code == "console.log('hi');"


def test_emotion_event():
    evt = EmotionEvent(mood="celebrating", effect="confetti")
    data = evt.model_dump()
    assert data["type"] == "reaction"
    assert data["mood"] == "celebrating"
    assert data["effect"] == "confetti"


def test_transcript_event():
    evt = TranscriptEvent(sender="gemini", text="Let's make it bouncy!")
    data = evt.model_dump()
    assert data["type"] == "transcript"
    assert data["sender"] == "gemini"
    assert data["text"] == "Let's make it bouncy!"


def test_status_event():
    evt = StatusEvent(state="listening", message="Connected: Gemini 3.8 Live")
    data = evt.model_dump()
    assert data["type"] == "status"
    assert data["state"] == "listening"
    assert data["message"] == "Connected: Gemini 3.8 Live"
