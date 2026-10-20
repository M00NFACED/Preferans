"""Сервер: WebSocket-протокол, статика, запуск."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import rules as R
from .game import (
    GameError,
    PHASE_LOBBY,
    PHASE_MATCH_END,
    PHASE_ROUND_END,
)
from .rooms import Connection, Room, RoomManager

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
# Меняем при изменении правил/клиента: клиент предупредит, если сервер старый.
APP_VERSION = "2026-10-20-3"

manager = RoomManager()


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(cleanup_loop())
    yield
    task.cancel()


app = FastAPI(title="Преферанс", docs_url=None, redoc_url=None, lifespan=lifespan)


class Session:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self.player_id: str | None = None
        self.room: Room | None = None
        self.seat: int | None = None


def _err(session: Session, code: str, message: str) -> None:
    asyncio.create_task(session.conn.send({"type": "error", "code": code, "message": message}))


async def _detach(session: Session) -> None:
    if session.room is not None and session.player_id is not None:
        room = session.room
        room.connections.pop(session.player_id, None)
        room.set_connected(session.player_id, False)
        await room.broadcast()
    session.room = None
    session.seat = None


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True, "rooms": len(manager.rooms)})


@app.get("/api/room/{code}")
async def room_info(code: str) -> JSONResponse:
    room = manager.get(code)
    if room is None:
        return JSONResponse({"ok": False}, status_code=404)
    return JSONResponse({"ok": True, "room": room.room_state()})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    conn = Connection(websocket)
    await conn.start()
    session = Session(conn)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(message, dict):
                continue
            try:
                await handle_message(session, message)
            except GameError as exc:
                await conn.send({"type": "error", "code": exc.code, "message": exc.message})
            except Exception as exc:  # не роняем соединение из-за одной ошибки
                await conn.send({"type": "error", "code": "internal", "message": str(exc)})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await _detach(session)
        await conn.close()


async def handle_message(session: Session, message: dict) -> None:
    kind = message.get("type")
    handler = HANDLERS.get(kind)
    if handler is None:
        return
    await handler(session, message)


# --------------------------------------------------------------------- хендлеры

async def handle_create(session: Session, message: dict) -> None:
    await _detach(session)
    name = (message.get("name") or "").strip()[:24] or "Игрок"
    player_id = message.get("player_id") or name
    options = message.get("options") or {}
    room = manager.create(
        {
            "variant": int(options.get("variant", R.VARIANT_SOCHI)),
            "max_bullet": int(options.get("max_bullet", 30)),
            "blind": bool(options.get("blind", True)),
        }
    )
    seat = room.add_human(name, player_id)
    room.connections[player_id] = session.conn
    session.player_id = player_id
    session.room = room
    session.seat = seat
    await session.conn.send({"type": "joined", "room": room.code, "seat": seat, "player_id": player_id})
    await room.broadcast()


async def handle_join(session: Session, message: dict) -> None:
    code = (message.get("code") or "").strip().upper()
    room = manager.get(code)
    if room is None:
        raise GameError("no_room", "Такой комнаты не существует.")
    seat_index = room.seat_of(message.get("player_id") or "")
    if seat_index is None:
        seat_index = room.add_human(
            (message.get("name") or "").strip()[:24] or "Игрок",
            message.get("player_id") or "guest",
        )
    room.connections[room.seats[seat_index]["player_id"]] = session.conn
    room.set_connected(room.seats[seat_index]["player_id"], True)
    session.player_id = room.seats[seat_index]["player_id"]
    session.room = room
    session.seat = seat_index
    await session.conn.send(
        {"type": "joined", "room": room.code, "seat": seat_index, "player_id": session.player_id}
    )
    await room.broadcast()


async def handle_resume(session: Session, message: dict) -> None:
    code = (message.get("code") or "").strip().upper()
    player_id = message.get("player_id") or ""
    room = manager.get(code)
    if room is None or not player_id:
        await session.conn.send({"type": "resume_failed", "reason": "no_room"})
        return
    seat_index = room.seat_of(player_id)
    if seat_index is None:
        await session.conn.send({"type": "resume_failed", "reason": "no_seat"})
        return
    room.connections[player_id] = session.conn
    room.set_connected(player_id, True)
    session.player_id = player_id
    session.room = room
    session.seat = seat_index
    await session.conn.send(
        {"type": "joined", "room": room.code, "seat": seat_index, "player_id": player_id}
    )
    await room.broadcast()


async def handle_leave(session: Session, message: dict) -> None:
    room = session.room
    if room is not None and session.player_id is not None:
        room.connections.pop(session.player_id, None)
        room.remove_player(session.player_id)
        if room.host_id is None:
            room.host_id = next(
                (s["player_id"] for s in room.seats if s and not s["is_bot"]), None
            )
        await room.broadcast()
        if all(seat is None for seat in room.seats):
            manager.remove(room.code)
    session.room = None
    session.seat = None
    await session.conn.send({"type": "left"})


async def handle_add_bot(session: Session, message: dict) -> None:
    room = session.room
    if room is None:
        raise GameError("no_room", "Вы не в комнате.")
    if room.game is not None and room.game.phase != PHASE_LOBBY:
        raise GameError("in_game", "Игра уже началась.")
    room.add_bot()
    await room.broadcast()


async def handle_remove_bot(session: Session, message: dict) -> None:
    room = session.room
    if room is None:
        raise GameError("no_room", "Вы не в комнате.")
    if room.game is not None and room.game.phase != PHASE_LOBBY:
        raise GameError("in_game", "Игра уже началась.")
    index = message.get("seat")
    if isinstance(index, int) and 0 <= index < len(room.seats):
        seat = room.seats[index]
        if seat and seat["is_bot"]:
            room.seats[index] = None
    await room.broadcast()


async def handle_start(session: Session, message: dict) -> None:
    room = session.room
    if room is None:
        raise GameError("no_room", "Вы не в комнате.")
    if room.game is not None and room.game.phase not in (PHASE_LOBBY, PHASE_MATCH_END):
        raise GameError("in_game", "Игра уже идёт.")
    if any(seat is None for seat in room.seats):
        raise GameError("not_enough_players", "Нужно трое игроков. Добавьте бота.")
    room.start_match()
    await room.broadcast()
    room.after_action()


async def handle_settings(session: Session, message: dict) -> None:
    room = session.room
    if room is None:
        raise GameError("no_room", "Вы не в комнате.")
    if room.game is not None and room.game.phase != PHASE_LOBBY:
        raise GameError("in_game", "Настройки меняются только в лобби.")
    variant = int(message.get("variant", room.options["variant"]))
    max_bullet = int(message.get("max_bullet", room.options["max_bullet"]))
    room.options["variant"] = variant if variant in R.VARIANT_NAMES else R.VARIANT_SOCHI
    room.options["max_bullet"] = max(5, min(50, max_bullet))
    if "blind" in message:
        room.options["blind"] = bool(message.get("blind"))
        if room.game is not None:
            room.game.blind_allowed = room.options["blind"]
    await room.broadcast()


async def handle_bid(session: Session, message: dict) -> None:
    room, seat = _require_turn(session)
    assert room is not None and seat is not None and room.game is not None
    kind = message.get("kind", "pass")
    contract = message.get("contract")
    blind = bool(message.get("blind"))
    room.game.bid(seat, kind, int(contract) if contract is not None else None, blind=blind)
    await room.broadcast()
    room.after_action()


async def handle_open_cards(session: Session, message: dict) -> None:
    room, seat = _require_turn(session)
    assert room is not None and seat is not None and room.game is not None
    room.game.open_cards(seat)
    await room.broadcast()
    room.after_action()


async def handle_whist_mode(session: Session, message: dict) -> None:
    room, seat = _require_turn(session)
    assert room is not None and seat is not None and room.game is not None
    room.game.whist_mode(seat, bool(message.get("dark")))
    await room.broadcast()
    room.after_action()


async def handle_drop(session: Session, message: dict) -> None:
    room, seat = _require_turn(session)
    assert room is not None and seat is not None and room.game is not None
    cards = message.get("cards") or []
    room.game.drop(seat, [int(c) for c in cards])
    await room.broadcast()
    room.after_action()


async def handle_declare(session: Session, message: dict) -> None:
    room, seat = _require_turn(session)
    assert room is not None and seat is not None and room.game is not None
    contract = int(message.get("contract", 0))
    without_three = bool(message.get("without_three"))
    room.game.declare(seat, contract, without_three)
    await room.broadcast()
    room.after_action()


async def handle_whist(session: Session, message: dict) -> None:
    room, seat = _require_turn(session)
    assert room is not None and seat is not None and room.game is not None
    room.game.whist(seat, message.get("kind", "pass"))
    await room.broadcast()
    room.after_action()


async def handle_catch_mizer(session: Session, message: dict) -> None:
    room, seat = _require_turn(session)
    assert room is not None and seat is not None and room.game is not None
    room.game.catch_mizer(seat, bool(message.get("accept")))
    await room.broadcast()
    room.after_action()


async def handle_play(session: Session, message: dict) -> None:
    room, seat = _require_turn(session)
    assert room is not None and seat is not None and room.game is not None
    room.game.play(seat, int(message.get("card")))
    await room.broadcast()
    room.after_action()


async def handle_next_round(session: Session, message: dict) -> None:
    room = session.room
    if room is None or room.game is None:
        raise GameError("no_room", "Вы не в комнате.")
    if room.game.phase != PHASE_ROUND_END:
        return
    room.start_next_round()
    await room.broadcast()
    room.after_action()


async def handle_new_match(session: Session, message: dict) -> None:
    room = session.room
    if room is None:
        raise GameError("no_room", "Вы не в комнате.")
    if room.game is None or room.game.phase != PHASE_MATCH_END:
        raise GameError("in_game", "Матч ещё не закончен.")
    room.reset_match()
    await room.broadcast()
    room.after_action()


def _require_turn(session: Session) -> tuple[Room | None, int | None]:
    room = session.room
    if room is None or room.game is None:
        raise GameError("no_room", "Вы не в комнате.")
    if session.seat is None:
        raise GameError("no_seat", "Вы не за игровым столом.")
    return room, session.seat


async def handle_ping(session: Session, message: dict) -> None:
    await session.conn.send({"type": "pong"})


HANDLERS = {
    "create": handle_create,
    "join": handle_join,
    "resume": handle_resume,
    "leave": handle_leave,
    "add_bot": handle_add_bot,
    "remove_bot": handle_remove_bot,
    "start": handle_start,
    "settings": handle_settings,
    "bid": handle_bid,
    "open_cards": handle_open_cards,
    "drop": handle_drop,
    "declare": handle_declare,
    "whist": handle_whist,
    "whist_mode": handle_whist_mode,
    "catch_mizer": handle_catch_mizer,
    "play": handle_play,
    "next_round": handle_next_round,
    "new_match": handle_new_match,
    "ping": handle_ping,
}


async def cleanup_loop() -> None:
    while True:
        await asyncio.sleep(60)
        manager.cleanup()


@app.on_event("startup")
async def on_startup() -> None:
    app.state.cleanup_task = asyncio.create_task(cleanup_loop())


# Статика подключается последней, иначе она перехватит /api и /ws
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        log_level="info",
    )
