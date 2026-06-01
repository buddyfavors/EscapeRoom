from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, model_validator

from escape_room.config import MINIGAMES_ENABLED, RFID_DEVICE_PATH, ROOT_DIR
from escape_room.game_engine import GameEngine
from escape_room.models import (
    BountyTheme,
    CodePools,
    DEFAULT_GOOD_CODES_PER_REWARD,
    DEFAULT_FINAL_COUNTDOWN_START_AFTER,
    DEFAULT_PUNISHMENT_LIMIT,
    DEFAULT_PUNISHMENT_LIMIT_ENABLED,
    UNLIMITED_PUNISHMENT_LIMIT,
    DEFAULT_REWARDS_TO_WIN,
    DEFAULT_RFIDS_PER_PUNISHMENT,
    DEFAULT_TIMER_MINUTES,
    Difficulty,
    GameMode,
    GameSnapshot,
    LockCounts,
    LockKind,
    LockSlot,
    RFID_GOOD_PERCENT,
    RFID_GOOD_PERCENT_BASE,
    RFID_PRD_BAD_INCREMENT,
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
from escape_room.storage import load_code_pools, save_code_pools_json, validate_codes_json
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
        {"minigames_enabled": MINIGAMES_ENABLED},
    )


class CodesTextBody(BaseModel):
    text: str


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


class GameStartBody(BaseModel):
    game_mode: GameMode = GameMode.breakout
    difficulty: Difficulty = Difficulty.medium
    digit3: int | None = Field(default=None, ge=0)
    letter5: int | None = Field(default=None, ge=0)
    digit4: int | None = Field(default=None, ge=0)
    locks: LockCounts | None = None
    punishment_limit: int | None = Field(default=None, ge=0, le=99)
    timer_minutes: int | None = Field(default=None, ge=1, le=180)
    rfids_per_punishment: int | None = Field(default=None, ge=1, le=99)
    good_codes_per_reward: int | None = Field(default=None, ge=1, le=99)
    rewards_to_win: int | None = Field(default=None, ge=1, le=99)
    bounty_theme: BountyTheme = BountyTheme.breakout
    final_countdown_enabled: bool = False
    final_countdown_start_after: int | None = Field(default=None, ge=1, le=99)

    @model_validator(mode="before")
    @classmethod
    def _normalize_lock_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        nested = out.get("locks")
        if isinstance(nested, dict):
            for key in ("digit3", "letter5", "digit4"):
                if key in nested and out.get(key) is None:
                    out[key] = nested[key]
        return out

    def lock_counts(self) -> LockCounts:
        if self.locks is not None:
            return self.locks
        if any(v is not None for v in (self.digit3, self.letter5, self.digit4)):
            return LockCounts(
                digit3=0 if self.digit3 is None else self.digit3,
                letter5=0 if self.letter5 is None else self.letter5,
                digit4=0 if self.digit4 is None else self.digit4,
            )
        return LockCounts()

    def resolved_punishment_limit(self) -> int:
        if self.game_mode is not GameMode.breakout:
            return UNLIMITED_PUNISHMENT_LIMIT
        if self.punishment_limit is not None:
            return self.punishment_limit
        return UNLIMITED_PUNISHMENT_LIMIT

    def resolved_timer_minutes(self) -> int:
        if self.timer_minutes is not None:
            return self.timer_minutes
        return DEFAULT_TIMER_MINUTES

    def resolved_rfids_per_punishment(self) -> int:
        if self.rfids_per_punishment is not None:
            return self.rfids_per_punishment
        return DEFAULT_RFIDS_PER_PUNISHMENT

    def resolved_good_codes_per_reward(self) -> int:
        if self.good_codes_per_reward is not None:
            return self.good_codes_per_reward
        return DEFAULT_GOOD_CODES_PER_REWARD

    def resolved_rewards_to_win(self) -> int:
        if self.rewards_to_win is not None:
            return self.rewards_to_win
        return DEFAULT_REWARDS_TO_WIN

    def resolved_final_countdown_start_after(self) -> int:
        if self.final_countdown_start_after is not None:
            return self.final_countdown_start_after
        return DEFAULT_FINAL_COUNTDOWN_START_AFTER


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
        "last_punishment": snap.last_punishment,
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


def _refresh_code_pools() -> CodePools:
    """Reload lock code pools from disk and keep the in-memory engine in sync."""
    pools = load_code_pools()
    state.engine.set_pools(pools)
    return pools


def _lock_setup_payload() -> dict[str, Any]:
    """Available pool sizes and default lock counts for the Play screen."""
    pools = _refresh_code_pools()
    return {
        "available": {
            "digit3": len(pools.digit3),
            "letter5": len(pools.letter5),
            "digit4": len(pools.digit4),
        },
            "defaults": LockCounts().model_dump(),
            "default_punishment_limit": DEFAULT_PUNISHMENT_LIMIT,
            "default_punishment_limit_enabled": DEFAULT_PUNISHMENT_LIMIT_ENABLED,
            "default_timer_minutes": DEFAULT_TIMER_MINUTES,
            "default_rfids_per_punishment": DEFAULT_RFIDS_PER_PUNISHMENT,
            "default_good_codes_per_reward": DEFAULT_GOOD_CODES_PER_REWARD,
            "default_rewards_to_win": DEFAULT_REWARDS_TO_WIN,
            "default_final_countdown_start_after": DEFAULT_FINAL_COUNTDOWN_START_AFTER,
            "gamemaster_name": load_room_settings().gamemaster_name,
            "game_modes": [m.value for m in GameMode],
            "bounty_themes": [t.value for t in BountyTheme],
            "rfid_base_good_percent": RFID_GOOD_PERCENT_BASE,
            "rfid_prd_increment_percent": {
                d.value: round(RFID_PRD_BAD_INCREMENT[d] * 100) for d in Difficulty
            },
            "rfid_luck": {d.value: RFID_GOOD_PERCENT[d] for d in Difficulty},
    }


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    state.main_loop = asyncio.get_running_loop()
    pools = load_code_pools()
    state.engine.set_pools(pools)
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
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "minigames_enabled": MINIGAMES_ENABLED,
            "lock_setup": _lock_setup_payload(),
        },
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    return _html(request, "settings.html")


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


def _lock_kind_label(kind: LockKind) -> str:
    if kind == "digit3":
        return "3-digit lock"
    if kind == "digit4":
        return "4-digit lockbox"
    if kind == "letter5":
        return "5-letter lock"
    return kind


def _programming_from_slots(slots: list[LockSlot]) -> list[dict[str, Any]]:
    return [
        {
            "index": i + 1,
            "kind": lock.kind,
            "kind_label": _lock_kind_label(lock.kind),
            "code": lock.code,
            "id": lock.id,
        }
        for i, lock in enumerate(slots)
    ]


@app.get("/api/game/setup")
async def game_setup() -> JSONResponse:
    """Pool sizes and defaults for the start-game form."""
    return JSONResponse(content=_lock_setup_payload())


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


@app.post("/api/game/preview")
async def game_preview(body: GameStartBody) -> JSONResponse:
    """Roll lock combinations for the Gamemaster before starting; start() reuses this preview."""
    try:
        counts = body.lock_counts()
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
async def game_start(body: GameStartBody) -> JSONResponse:
    try:
        snap = state.engine.start(
            body.difficulty,
            body.lock_counts(),
            body.resolved_punishment_limit(),
            game_mode=body.game_mode,
            timer_minutes=body.resolved_timer_minutes(),
            rfids_per_punishment=body.resolved_rfids_per_punishment(),
            good_codes_per_reward=body.resolved_good_codes_per_reward(),
            rewards_to_win=body.resolved_rewards_to_win(),
            bounty_theme=body.bounty_theme,
            final_countdown_enabled=body.final_countdown_enabled,
            final_countdown_start_after=body.resolved_final_countdown_start_after(),
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
