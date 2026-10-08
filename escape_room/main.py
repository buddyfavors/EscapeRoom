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

from escape_room.config import MINIGAMES_ENABLED, RFID_DEVICE_PATH, ROOT_DIR
from escape_room.game_engine import GameEngine, lock_kind_label
from escape_room.models import (
    UNLIMITED_PUNISHMENT_LIMIT,
    Difficulty,
    GameMode,
    GameSnapshot,
    LockCounts,
    LockSlot,
    VirtualBadge,
    VirtualScanOutcome,
)
from escape_room.rfid import create_rfid_listener
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
        {
            "minigames_enabled": MINIGAMES_ENABLED,
            "game_active": state.engine.snapshot() is not None,
        },
    )


class RfidTagsTextBody(BaseModel):
    text: str


class PunishmentsTextBody(BaseModel):
    text: str


class RoomSettingsBody(BaseModel):
    gamemaster_name: str = Field(min_length=1, max_length=40)
    bad_scan_phrases: list[str] = Field(min_length=1)
    wildcard_free_good_tag: str | None = None
    wildcard_trump_tag: str | None = None
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
        "difficulty": snap.difficulty.value,
        "game_mode": snap.game_mode.value,
        "phase": snap.phase.value,
        "rfid_good_percent": snap.rfid_good_percent,
        "rfid_bad_chance_percent": snap.rfid_bad_chance_percent,
        "started_at_iso": snap.started_at_iso,
        "won": snap.won,
        "timer_duration_sec": snap.timer_duration_sec,
        "timer_ends_at_iso": snap.timer_ends_at_iso,
        "timer_seconds_remaining": snap.timer_seconds_remaining,
        "deadline_cycle": snap.deadline_cycle,
        "final_countdown_enabled": snap.final_countdown_enabled,
        "final_countdown_start_after": snap.final_countdown_start_after,
        "gamemaster_name": snap.gamemaster_name,
        "punishment_resolution": snap.punishment_resolution.value,
        "pending_punishment_label": snap.pending_punishment_label,
        "pending_punishment_message": snap.pending_punishment_message,
        "pending_punishment_is_minigame": snap.pending_punishment_is_minigame,
        "punishment_timer_seconds_remaining": snap.punishment_timer_seconds_remaining,
        "punishment_timer_kind": snap.punishment_timer_kind,
        "wildcard_free_good_used": snap.wildcard_free_good_used,
        "wildcard_trump_used": snap.wildcard_trump_used,
        "wildcard_free_good_cooldown_seconds": snap.wildcard_free_good_cooldown_seconds,
        "wildcard_skip_cooldown_seconds": snap.wildcard_skip_cooldown_seconds,
        "rfids_per_punishment": snap.rfids_per_punishment,
        "rfids_collected": snap.rfids_collected,
        "bounty_theme": snap.bounty_theme.value if snap.bounty_theme else None,
        "good_codes_per_reward": snap.good_codes_per_reward,
        "good_codes_progress": snap.good_codes_progress,
        "rewards_earned": snap.rewards_earned,
        "rewards_to_win": snap.rewards_to_win,
        "bad_code_effect": snap.bad_code_effect,
        "bad_codes_progress": snap.bad_codes_progress,
        "bad_codes_goal": snap.bad_codes_goal,
        "punishments_received": snap.punishments_received,
        "punishments_limit": snap.punishments_limit,
        "gm_won": snap.gm_won,
        "game_over": snap.game_over,
        "good_rfid_progress": snap.good_rfid_progress,
        "good_rfid_goal": snap.good_rfid_goal,
        "minigames_enabled": snap.minigames_enabled,
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


@app.get("/minigames", response_class=HTMLResponse)
async def minigames_hub(request: Request) -> HTMLResponse:
    if not MINIGAMES_ENABLED:
        return _html(request, "minigames_disabled.html")
    return _html(request, "minigames.html")


@app.get("/minigames/reaction-rush", response_class=HTMLResponse)
async def minigame_reaction_rush(request: Request) -> HTMLResponse:
    if not MINIGAMES_ENABLED:
        return _html(request, "minigames_disabled.html")
    return _html(request, "reaction_rush.html")


@app.get("/minigames/whack-mole", response_class=HTMLResponse)
async def minigame_whack_mole(request: Request) -> HTMLResponse:
    if not MINIGAMES_ENABLED:
        return _html(request, "minigames_disabled.html")
    return _html(request, "whack_mole.html")


@app.get("/minigames/rps", response_class=HTMLResponse)
async def minigame_rps(request: Request) -> HTMLResponse:
    if not MINIGAMES_ENABLED:
        return _html(request, "minigames_disabled.html")
    return _html(request, "rps.html")


@app.get("/minigames/simon", response_class=HTMLResponse)
async def minigame_simon(request: Request) -> HTMLResponse:
    if not MINIGAMES_ENABLED:
        return _html(request, "minigames_disabled.html")
    return _html(request, "simon.html")


@app.get("/minigames/pattern", response_class=HTMLResponse)
async def minigame_pattern(request: Request) -> HTMLResponse:
    if not MINIGAMES_ENABLED:
        return _html(request, "minigames_disabled.html")
    return _html(request, "pattern.html")


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


@app.get("/api/room-settings")
async def get_room_settings() -> JSONResponse:
    settings = load_room_settings()
    return JSONResponse(content=settings.model_dump(mode="json"))


@app.post("/api/room-settings")
async def post_room_settings(body: RoomSettingsBody) -> JSONResponse:
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
    """Gamemaster console: reward badge, skip badge, or complete the pending punishment."""
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
    try:
        snap = state.engine.start(
            Difficulty.medium,
            counts,
            UNLIMITED_PUNISHMENT_LIMIT,
            game_mode=GameMode.breakout,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # Engine emits game_started; also return for clients without WS
    return JSONResponse(content={"ok": True, "snapshot": _redact_snapshot(snap)})


@app.post("/api/game/punishment-complete")
async def game_punishment_complete() -> JSONResponse:
    """Deadline mode: call after a minigame punishment finishes."""
    ok = state.engine.complete_punishment()
    if not ok:
        raise HTTPException(status_code=400, detail="No punishment waiting to complete.")
    snap = state.engine.snapshot()
    return JSONResponse(content={"ok": True, "snapshot": _redact_snapshot(snap)})


@app.post("/api/game/stop")
async def game_stop() -> JSONResponse:
    state.engine.stop()
    return JSONResponse(content={"ok": True})


@app.get("/api/minigames")
async def minigames_list() -> JSONResponse:
    if not MINIGAMES_ENABLED:
        return JSONResponse(content=[])
    from escape_room.minigames import list_minigames

    return JSONResponse(
        content=[m.__dict__ for m in list_minigames()],
    )


@app.websocket("/ws/minigame/reaction-rush")
async def websocket_reaction_rush(ws: WebSocket) -> None:
    await ws.accept()
    if not MINIGAMES_ENABLED:
        await ws.close(code=4000)
        return
    try:
        await run_reaction_rush_session(ws)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/minigame/whack-mole")
async def websocket_whack_mole(ws: WebSocket) -> None:
    await ws.accept()
    if not MINIGAMES_ENABLED:
        await ws.close(code=4000)
        return
    try:
        await run_whack_mole_session(ws)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/minigame/rps")
async def websocket_rps(ws: WebSocket) -> None:
    await ws.accept()
    if not MINIGAMES_ENABLED:
        await ws.close(code=4000)
        return
    try:
        await run_rps_session(ws)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/minigame/simon")
async def websocket_simon(ws: WebSocket) -> None:
    await ws.accept()
    if not MINIGAMES_ENABLED:
        await ws.close(code=4000)
        return
    try:
        await run_simon_session(ws)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/minigame/pattern")
async def websocket_pattern(ws: WebSocket) -> None:
    await ws.accept()
    if not MINIGAMES_ENABLED:
        await ws.close(code=4000)
        return
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
