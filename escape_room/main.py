from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from escape_room.config import RFID_DEVICE_PATH, ROOT_DIR
from escape_room.game_engine import GameEngine, lock_kind_label
from escape_room.models import (
    UNLIMITED_PUNISHMENT_LIMIT,
    GameSnapshot,
    LockCounts,
    LockSlot,
    VirtualBadge,
    VirtualScanOutcome,
)
from escape_room.rfid import create_rfid_listener
from escape_room.rfid_format import normalize_rfid_tag
from escape_room.rfid_store import load_rfid_tags, save_rfid_tags_text, validate_rfid_tags_text
from escape_room.punishments_store import (
    load_punishments,
    save_punishments_text,
    validate_punishments_text,
)
from escape_room.room_settings_store import (
    RoomSettings,
    load_room_settings,
    save_room_settings,
    validate_room_settings_json,
)

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))


def _html(request: Request, name: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        name,
        {"game_active": state.engine.snapshot() is not None},
    )


class RfidTagsTextBody(BaseModel):
    text: str


class PunishmentsTextBody(BaseModel):
    text: str


class RoomSettingsBody(BaseModel):
    gamemaster_name: str = Field(min_length=1, max_length=40)
    bad_scan_phrases: list[str] = Field(min_length=1)
    reward_badge_tag: str | None = None
    gamemaster_complete_tag: str | None = None
    physical_wheel: bool = False
    lockbox_tags: list[str] = Field(default_factory=list)


class VirtualScanBody(BaseModel):
    outcome: VirtualScanOutcome = "roll"


class VirtualBadgeBody(BaseModel):
    badge: VirtualBadge


def _redact_snapshot(snap: GameSnapshot | None) -> dict[str, Any] | None:
    if snap is None:
        return None
    return {
        "phase": snap.phase.value,
        "rfid_good_percent": snap.rfid_good_percent,
        "rfid_bad_chance_percent": snap.rfid_bad_chance_percent,
        "started_at_iso": snap.started_at_iso,
        "intro_active": snap.intro_active,
        "finished_at_iso": snap.finished_at_iso,
        "won": snap.won,
        "gamemaster_name": snap.gamemaster_name,
        "punishment_resolution": snap.punishment_resolution.value,
        "pending_punishment_label": snap.pending_punishment_label,
        "pending_punishment_message": snap.pending_punishment_message,
        "punishment_timer_seconds_remaining": snap.punishment_timer_seconds_remaining,
        "punishment_timer_kind": snap.punishment_timer_kind,
        "wildcard_free_good_used": snap.wildcard_free_good_used,
        "wildcard_free_good_cooldown_seconds": snap.wildcard_free_good_cooldown_seconds,
        "bad_codes_progress": snap.bad_codes_progress,
        "bad_codes_goal": snap.bad_codes_goal,
        "punishments_received": snap.punishments_received,
        "punishments_limit": snap.punishments_limit,
        "gm_won": snap.gm_won,
        "game_over": snap.game_over,
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
        self.rfid = create_rfid_listener(RFID_DEVICE_PATH, self._on_rfid_buffer)
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
    tags = load_rfid_tags()
    state.engine.set_rfid_tags(tags)
    state.engine.set_punishments(load_punishments())
    state.engine.set_room_settings(load_room_settings())
    unsub = state.engine.subscribe(state._schedule_broadcast)

    if state.rfid.start():
        logger.info(
            "RFID listener started (%s) — device spec %s",
            state.rfid.backend_name,
            RFID_DEVICE_PATH,
        )
    else:
        logger.info(
            "RFID listener not started (%s backend unavailable on this platform).",
            getattr(state.rfid, "backend_name", "unknown"),
        )

    yield

    state.rfid.stop()
    unsub()
    state.main_loop = None


app = FastAPI(title="KnottyBytes Escape Room", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return _html(request, "index.html")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    return _html(request, "settings.html")


@app.get("/gamemaster", response_class=HTMLResponse)
async def gamemaster_page(request: Request) -> HTMLResponse:
    return _html(request, "gamemaster.html")


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
    tags, duplicates_removed = save_rfid_tags_text(body.text)
    state.engine.set_rfid_tags(tags)
    return JSONResponse(
        content={"ok": True, "count": len(tags.tags), "duplicates_removed": duplicates_removed}
    )


@app.get("/api/punishments")
async def get_punishments_raw() -> JSONResponse:
    from escape_room.config import PUNISHMENTS_FILE

    if not PUNISHMENTS_FILE.exists():
        default = (
            "# One punishment per line. Use 'Title: details' to show a short title above the details.\n"
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


@app.get("/api/room-settings")
async def get_room_settings() -> JSONResponse:
    settings = load_room_settings()
    return JSONResponse(content=settings.model_dump(mode="json"))


@app.post("/api/room-settings")
async def post_room_settings(body: RoomSettingsBody) -> JSONResponse:
    for label, raw in (
        ("Reward badge", body.reward_badge_tag),
        ("Gamemaster badge", body.gamemaster_complete_tag),
    ):
        if raw and raw.strip() and normalize_rfid_tag(raw) is None:
            raise HTTPException(status_code=400, detail=f"{label} must be a 10-digit tag ID.")
    settings = RoomSettings.model_validate(body.model_dump())
    save_room_settings(settings)
    state.engine.set_room_settings(settings)
    return JSONResponse(content={"ok": True, "settings": settings.model_dump(mode="json")})


def _programming_from_slots(slots: list[LockSlot]) -> list[dict[str, Any]]:
    return [
        {
            "index": i + 1,
            "kind": lock.kind,
            "kind_label": lock_kind_label(lock.kind),
            "code": lock.code,
            "id": lock.id,
        }
        for i, lock in enumerate(slots)
    ]


@app.get("/api/game/status")
async def game_status() -> JSONResponse:
    snap = state.engine.snapshot()
    return JSONResponse(content={"active": snap is not None, "snapshot": _redact_snapshot(snap)})


@app.get("/api/gm/snapshot")
async def gm_snapshot() -> JSONResponse:
    """Full snapshot including lock codes (GM / backstage monitor only)."""
    snap = state.engine.snapshot()
    if snap is None:
        return JSONResponse(content={"active": False, "snapshot": None, "programming": []})
    return JSONResponse(
        content={
            "active": True,
            "snapshot": snap.model_dump(mode="json"),
            "rfid_good_percent": snap.rfid_good_percent,
            "programming": _programming_from_slots(snap.locks),
        }
    )


@app.post("/api/gm/virtual-scan")
async def gm_virtual_scan(body: VirtualScanBody) -> JSONResponse:
    """Gamemaster console: scan a virtual approved RFID (roll, forced good, or forced bad)."""
    result = state.engine.submit_virtual_rfid(body.outcome)
    snap = state.engine.snapshot()
    return JSONResponse(
        content={"result": result.model_dump(mode="json"), "snapshot": _redact_snapshot(snap)}
    )


@app.post("/api/gm/virtual-badge")
async def gm_virtual_badge(body: VirtualBadgeBody) -> JSONResponse:
    """Gamemaster console: reward badge (starts an armed game or skips a pending punishment), complete the pending punishment, or open a lockbox."""
    result = state.engine.submit_virtual_badge(body.badge)
    snap = state.engine.snapshot()
    return JSONResponse(
        content={"result": result.model_dump(mode="json"), "snapshot": _redact_snapshot(snap)}
    )


@app.post("/api/game/preview")
async def game_preview(counts: LockCounts) -> JSONResponse:
    """Roll lock combinations for the Gamemaster before starting; start() reuses this preview."""
    try:
        slots = state.engine.preview_locks(counts)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return JSONResponse(
        content={
            "ok": True,
            "counts": counts.model_dump(),
            "programming": _programming_from_slots(slots),
        }
    )


@app.post("/api/game/start")
async def game_start(counts: LockCounts) -> JSONResponse:
    """Arm the room; play begins when the Gamemaster scans the reward badge (or /api/game/begin)."""
    try:
        snap = state.engine.start(counts, UNLIMITED_PUNISHMENT_LIMIT, wait_for_badge=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # Engine emits game_armed; also return for clients without WS
    return JSONResponse(content={"ok": True, "snapshot": _redact_snapshot(snap)})


@app.post("/api/game/begin")
async def game_begin() -> JSONResponse:
    snap = state.engine.begin()
    if snap is None:
        raise HTTPException(status_code=400, detail="No game is waiting to start.")
    return JSONResponse(content={"ok": True, "snapshot": _redact_snapshot(snap)})


@app.post("/api/game/intro-done")
async def game_intro_done() -> JSONResponse:
    """The play screen closed the intro; badges go back to their normal effects."""
    return JSONResponse(content={"ok": True, "ended": state.engine.end_intro()})


@app.post("/api/game/stop")
async def game_stop() -> JSONResponse:
    state.engine.stop()
    return JSONResponse(content={"ok": True})


@app.websocket("/ws")
async def websocket_display(ws: WebSocket) -> None:
    await state.ws.connect(ws)
    try:
        snap = state.engine.snapshot()
        await ws.send_json({"type": "hello", "snapshot": _redact_snapshot(snap)})
        while True:
            # Keep-alive; ignore incoming for now.
            await ws.receive_text()
    except WebSocketDisconnect:
        state.ws.disconnect(ws)


def create_app() -> FastAPI:
    return app
