"""Gemini: Player 2 - Backend Gateway FastAPI Application."""

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.conductor import LiveConductor
from backend.constants import DEFAULT_BREAKOUT_CODE
from backend.session import LiveSessionManager, handle_live_session

__all__ = [
    "DEFAULT_BREAKOUT_CODE",
    "LiveConductor",
    "LiveSessionManager",
    "app",
    "handle_live_session",
]

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hellogemini")

app = FastAPI(title="Gemini: Player 2 Backend Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    """Health check endpoint providing status and configuration info."""
    has_api_key = bool(
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_GENAI_USE_VERTEXAI")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
    )
    return {
        "status": "healthy",
        "service": "Gemini: Player 2 Gateway",
        "has_api_key": has_api_key,
        "vertex": bool(
            os.getenv("GOOGLE_GENAI_USE_VERTEXAI")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
        ),
    }


@app.get("/api/starter-code")
async def get_starter_code():
    """Returns the default arcade breakout game starter code."""
    return {"code": DEFAULT_BREAKOUT_CODE}


@app.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    """WebSocket gateway delegating client sessions to LiveSessionManager."""
    await handle_live_session(websocket, conductor_cls=LiveConductor)


# Mount frontend dist if it exists
frontend_dist_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist"
)
if os.path.exists(frontend_dist_path):
    app.mount(
        "/", StaticFiles(directory=frontend_dist_path, html=True), name="frontend"
    )
elif os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
