from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from escape_room.config import RFID_DEVICE_PATH, ROOT_DIR
from escape_room.game_engine import GameEngine
from escape_room.models import Difficulty, GameSnapshot
from escape_room.rfid import RfidKeyboardListener
from escape_room.rfid_store import load_rfid_tags, save_rfid_tags_text, validate_rfid_tags_text
from escape_room.punishments_store import (
    load_punishments,
    save_punishments_text,
    validate_punishments_text,
)
from escape_room.minigames.ws_reaction_rush import run_reaction_rush_session
from escape_room.minigames.ws_whack_mole import run_whack_mole_session
from escape_room.minigames.ws_rps import run_rps_session
from escape_room.minigames.ws_simon import run_simon_session
from escape_room.minigames.ws_pattern import run_pattern_session
from escape_room.storage import load_code_pools, save_code_pools_json, validate_codes_json

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))


class CodesTextBody(BaseModel):
    text: str


class RfidTagsTextBody(BaseModel):
    text: str


class PunishmentsTextBody(BaseModel):
    text: str


class GameStartBody(BaseModel):
    difficulty: Difficulty = Difficulty.easy


def _redact_snapshot(snap: GameSnapshot | None) -> dict[str, Any] | None:
    if snap is None:
        return None
    return {
        "difficulty": snap.difficulty.value,
        "started_at_iso": snap.started_at_iso,
        "won": snap.won,
        "bad_codes_progress": snap.bad_codes_progress,
        "bad_codes_goal": snap.bad_codes_goal,
        "good_rfid_progress": snap.good_rfid_progress,
        "good_rfid_goal": snap.good_rfid_goal,
        "locks": [
            {
                "id": l.id,
                "kind": l.kind,
                "solved": l.solved,
                "clues": list(l.revealed),
                "fully_revealed": bool(l.revealed) and all(c is not None for c in l.revealed),
            }
            for l in snap.locks
        ],
        "remaining": sum(1 for l in snap.locks if not l.solved),
        "total": len(snap.locks),
    }


def _redact_event(event: dict[str, Any]) -> dict[str, Any]:
    out = dict(event)
    snap = event.get("snapshot")
    if snap is None:
        return out
    try:
        gs = GameSnapshot.model_validate(snap)
    except Exception:
        return out
    out["snapshot"] = _redact_snapshot(gs)
    return out


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def broadcast_json(self, message: dict[str, Any]) -> None:
        async with self._lock:
            clients = list(self._clients)
        dead: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


class AppState:
    def __init__(self) -> None:
        self.engine = GameEngine()
        self.ws = ConnectionManager()
        self.rfid = RfidKeyboardListener(RFID_DEVICE_PATH, self._on_rfid_buffer)
        self.main_loop: asyncio.AbstractEventLoop | None = None

    def _on_rfid_buffer(self, buffer: str) -> None:
        self.engine.submit_code(buffer)

    def _schedule_broadcast(self, event: dict[str, Any]) -> None:
        loop = self.main_loop
        if loop is None:
            return
        payload = _redact_event(event)

        async def _send() -> None:
            await self.ws.broadcast_json(payload)

        asyncio.run_coroutine_threadsafe(_send(), loop)


state = AppState()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    state.main_loop = asyncio.get_running_loop()
    pools = load_code_pools()
    state.engine.set_pools(pools)
    tags = load_rfid_tags()
    state.engine.set_rfid_tags(tags)
    state.engine.set_punishments(load_punishments())
    unsub = state.engine.subscribe(state._schedule_broadcast)

    if state.rfid.start():
        logger.info("RFID listener started on %s", RFID_DEVICE_PATH)
    else:
        logger.info("RFID listener not started (missing evdev or device).")

    yield

    state.rfid.stop()
    unsub()
    state.main_loop = None


app = FastAPI(title="KnottyBytes Escape Room", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("settings.html", {"request": request})


@app.get("/minigames", response_class=HTMLResponse)
async def minigames_hub(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("minigames.html", {"request": request})


@app.get("/minigames/reaction-rush", response_class=HTMLResponse)
async def minigame_reaction_rush(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("reaction_rush.html", {"request": request})


@app.get("/minigames/whack-mole", response_class=HTMLResponse)
async def minigame_whack_mole(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("whack_mole.html", {"request": request})


@app.get("/minigames/rps", response_class=HTMLResponse)
async def minigame_rps(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("rps.html", {"request": request})


@app.get("/minigames/simon", response_class=HTMLResponse)
async def minigame_simon(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("simon.html", {"request": request})


@app.get("/minigames/pattern", response_class=HTMLResponse)
async def minigame_pattern(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("pattern.html", {"request": request})


@app.get("/api/codes")
async def get_codes_raw() -> JSONResponse:
    from escape_room.config import CODES_FILE

    if not CODES_FILE.exists():
        return JSONResponse(content={"text": "{}"})
    return JSONResponse(content={"text": CODES_FILE.read_text(encoding="utf-8")})


@app.post("/api/codes")
async def post_codes_raw(body: CodesTextBody) -> JSONResponse:
    text = body.text
    ok, err = validate_codes_json(text)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    pools = save_code_pools_json(text)
    state.engine.set_pools(pools)
    return JSONResponse(content={"ok": True})


@app.get("/api/rfid-tags")
async def get_rfid_tags_raw() -> JSONResponse:
    from escape_room.config import RFID_TAGS_FILE

    if not RFID_TAGS_FILE.exists():
        default = (
            "# One 10-digit tag per line. Lines starting with '#' are ignored.\n"
            "# Good vs bad outcome is rolled per scan by the game engine.\n"
        )
        return JSONResponse(content={"text": default})
    return JSONResponse(content={"text": RFID_TAGS_FILE.read_text(encoding="utf-8")})


@app.post("/api/rfid-tags")
async def post_rfid_tags_raw(body: RfidTagsTextBody) -> JSONResponse:
    ok, err = validate_rfid_tags_text(body.text)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    tags = save_rfid_tags_text(body.text)
    state.engine.set_rfid_tags(tags)
    return JSONResponse(content={"ok": True, "count": len(tags.tags)})


@app.get("/api/punishments")
async def get_punishments_raw() -> JSONResponse:
    from escape_room.config import PUNISHMENTS_FILE

    if not PUNISHMENTS_FILE.exists():
        default = (
            "# One punishment per line. Prefixes: 'minigame', 'minigame:<slug>', 'text:<msg>'.\n"
            "minigame\nminigame\n"
        )
        return JSONResponse(content={"text": default, "count": 0})
    text = PUNISHMENTS_FILE.read_text(encoding="utf-8")
    entries = state.engine.get_punishments()
    return JSONResponse(content={"text": text, "count": len(entries)})


@app.post("/api/punishments")
async def post_punishments_raw(body: PunishmentsTextBody) -> JSONResponse:
    ok, err = validate_punishments_text(body.text)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    entries = save_punishments_text(body.text)
    state.engine.set_punishments(entries)
    return JSONResponse(content={"ok": True, "count": len(entries)})


@app.get("/api/game/status")
async def game_status() -> JSONResponse:
    snap = state.engine.snapshot()
    return JSONResponse(content={"active": snap is not None, "snapshot": _redact_snapshot(snap)})


@app.get("/api/gm/snapshot")
async def gm_snapshot() -> JSONResponse:
    """Full snapshot including lock codes (GM / backstage monitor only)."""
    snap = state.engine.snapshot()
    if snap is None:
        return JSONResponse(content={"active": False, "snapshot": None})
    return JSONResponse(content={"active": True, "snapshot": snap.model_dump(mode="json")})


@app.post("/api/game/start")
async def game_start(body: GameStartBody) -> JSONResponse:
    difficulty = body.difficulty
    try:
        snap = state.engine.start(difficulty)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # Engine emits game_started; also return for clients without WS
    return JSONResponse(content={"ok": True, "snapshot": _redact_snapshot(snap)})


@app.post("/api/game/stop")
async def game_stop() -> JSONResponse:
    state.engine.stop()
    return JSONResponse(content={"ok": True})


@app.get("/api/minigames")
async def minigames_list() -> JSONResponse:
    from escape_room.minigames import list_minigames

    return JSONResponse(
        content=[m.__dict__ for m in list_minigames()],
    )


@app.websocket("/ws/minigame/reaction-rush")
async def websocket_reaction_rush(ws: WebSocket) -> None:
    await ws.accept()
    try:
        await run_reaction_rush_session(ws)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/minigame/whack-mole")
async def websocket_whack_mole(ws: WebSocket) -> None:
    await ws.accept()
    try:
        await run_whack_mole_session(ws)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/minigame/rps")
async def websocket_rps(ws: WebSocket) -> None:
    await ws.accept()
    try:
        await run_rps_session(ws)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/minigame/simon")
async def websocket_simon(ws: WebSocket) -> None:
    await ws.accept()
    try:
        await run_simon_session(ws)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/minigame/pattern")
async def websocket_pattern(ws: WebSocket) -> None:
    await ws.accept()
    try:
        await run_pattern_session(ws)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws")
async def websocket_display(ws: WebSocket) -> None:
    await state.ws.connect(ws)
    try:
        snap = state.engine.snapshot()
        await ws.send_json({"type": "hello", "snapshot": _redact_snapshot(snap)})
        while True:
            # Keep-alive; ignore incoming for now (future: GM commands / minigames).
            await ws.receive_text()
    except WebSocketDisconnect:
        state.ws.disconnect(ws)


def create_app() -> FastAPI:
    return app
