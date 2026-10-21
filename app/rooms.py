"""Комнаты: создание, посадка игроков, боты, рассылка состояния."""

from __future__ import annotations

import asyncio
import random
import string
import uuid

from . import bot as bot_ai
from . import cards as C
from . import rules as R
from .game import (
    Game,
    GameError,
    PHASE_AUCTION,
    PHASE_CATCH_MIZER,
    PHASE_DECLARE,
    PHASE_DROP,
    PHASE_LOBBY,
    PHASE_MATCH_END,
    PHASE_PLAYING,
    PHASE_ROUND_END,
    PHASE_WHIST,
    PHASE_WHIST_MODE,
    Player,
    ROUND_MIZER,
)

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
BOT_DELAY = (0.7, 1.6)
AUTO_NEXT_ROUND_DELAY = 25.0
AUTO_MOVE_TIMEOUT = 45.0
TRICK_SHOW_TIME = 2.6  # сколько показываем собранную взятку перед розыгрышем


def normalize_options(options: dict) -> dict:
    """Проверяет и приводит параметры комнаты к допустимым значениям."""
    try:
        variant = int(options.get("variant", R.VARIANT_SOCHI))
        max_bullet = int(options.get("max_bullet", 30))
    except (TypeError, ValueError) as exc:
        raise GameError(
            "bad_options", "variant и max_bullet должны быть числами."
        ) from exc
    if variant not in R.VARIANT_NAMES:
        raise GameError("bad_options", "Неизвестный вариант игры.")
    if max_bullet not in R.BULLET_LENGTHS:
        raise GameError(
            "bad_options",
            "Длина пули должна быть одной из: "
            + ", ".join(str(value) for value in R.BULLET_LENGTHS)
            + ".",
        )
    blind = options.get("blind", True)
    if not isinstance(blind, bool):
        blind = str(blind).strip().lower() in ("1", "true", "yes", "on")
    return {"variant": variant, "max_bullet": max_bullet, "blind": blind}


class Connection:
    """Обёртка над WebSocket: очередь сообщений + фоновой писатель."""

    def __init__(self, ws):
        self.ws = ws
        self.queue: asyncio.Queue = asyncio.Queue()
        self.writer: asyncio.Task | None = None
        self.closed = False

    async def start(self) -> None:
        self.writer = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while True:
                message = await self.queue.get()
                if message is None:
                    break
                await self.ws.send_json(message)
        except Exception:
            pass
        finally:
            self.closed = True

    async def send(self, data: dict) -> None:
        if self.closed:
            return
        await self.queue.put(data)

    async def close(self) -> None:
        self.closed = True
        await self.queue.put(None)
        if self.writer is not None:
            self.writer.cancel()


class Room:
    def __init__(self, code: str, options: dict, rng: random.Random):
        self.code = code
        self.options = normalize_options(options)
        self.rng = rng
        self.seats: list[dict | None] = [None, None, None]
        self.connections: dict[str, Connection] = {}
        self.game: Game | None = None
        self.host_id: str | None = None
        self.bot_task: asyncio.Task | None = None
        self.next_round_task: asyncio.Task | None = None
        self.auto_move_task: asyncio.Task | None = None
        self.resolve_task: asyncio.Task | None = None
        self._bot_counter = 0
        self.lock = asyncio.Lock()

    # ------------------------------------------------------------------ игроки

    def free_seat(self) -> int | None:
        for index, seat in enumerate(self.seats):
            if seat is None:
                return index
        return None

    def is_host(self, player_id: str) -> bool:
        return self.host_id == player_id

    def seat_of(self, player_id: str) -> int | None:
        for index, seat in enumerate(self.seats):
            if seat and seat["player_id"] == player_id:
                return index
        return None

    def add_human(self, name: str, player_id: str) -> int:
        index = self.free_seat()
        if index is None:
            raise GameError("room_full", "В комнате уже трое.")
        self.seats[index] = {
            "player_id": player_id,
            "name": name[:24] or "Игрок",
            "is_bot": False,
            "connected": True,
        }
        if self.host_id is None:
            self.host_id = player_id
        if self.game is not None:
            self.game.players[index].name = self.seats[index]["name"]
        return index

    def add_bot(self) -> int:
        index = self.free_seat()
        if index is None:
            raise GameError("room_full", "В комнате уже трое.")
        self._bot_counter += 1
        used = {s["name"] for s in self.seats if s}
        name = bot_ai.random_name(self.rng)
        attempt = 0
        while name in used and attempt < 20:
            name = bot_ai.random_name(self.rng)
            attempt += 1
        if name in used:
            name = f"{name} {self._bot_counter}"
        self.seats[index] = {
            "player_id": f"bot-{uuid.uuid4().hex[:8]}",
            "name": name,
            "is_bot": True,
            "connected": True,
        }
        return index

    def remove_seat(self, index: int) -> None:
        seat = self.seats[index]
        if seat is None or seat["is_bot"]:
            if seat is not None:
                self.seats[index] = None
            return
        pid = seat["player_id"]
        self.seats[index] = None
        if self.game is not None:
            self.game.players[index].folded = True
        if self.host_id == pid:
            self.host_id = next(
                (s["player_id"] for s in self.seats if s and not s["is_bot"]), None
            )

    def remove_player(self, player_id: str) -> None:
        index = self.seat_of(player_id)
        if index is None:
            return
        seat = self.seats[index]
        if seat["is_bot"]:
            self.seats[index] = None
            return
        if self.game is not None and self.game.phase != PHASE_LOBBY:
            seat["connected"] = False
            if self.game.players[index] is not None:
                self.game.players[index].connected = False
            return
        self.remove_seat(index)

    def set_connected(self, player_id: str, value: bool) -> None:
        index = self.seat_of(player_id)
        if index is None:
            return
        seat = self.seats[index]
        seat["connected"] = value
        if self.game is not None:
            self.game.players[index].connected = value

    # ------------------------------------------------------------------ матч

    def start_match(self) -> None:
        self._cancel(self.resolve_task)
        self.resolve_task = None
        players: list[Player] = []
        for index, seat in enumerate(self.seats):
            if seat is None:
                raise GameError("not_enough_players", "Нужно трое игроков.")
            players.append(
                Player(seat=index, pid=seat["player_id"], name=seat["name"], is_bot=seat["is_bot"])
            )
        self.game = Game(
            players,
            variant=self.options["variant"],
            max_bullet=self.options["max_bullet"],
            blind_allowed=bool(self.options.get("blind")),
        )
        self.game.start_round()

    def start_next_round(self) -> None:
        if self.game is None:
            return
        self._cancel(self.resolve_task)
        self.resolve_task = None
        if self.game.match_over():
            self.game.phase = PHASE_MATCH_END
            return
        self.game.start_round()
        self._cancel(self.next_round_task)
        self.next_round_task = None

    def reset_match(self) -> None:
        if self.game is not None:
            for player in self.game.players:
                player.bullet = 0
                player.mountain = 0
                player.vists = 0
        self.start_match()

    # ------------------------------------------------------------- рассылка

    def room_state(self) -> dict:
        return {
            "code": self.code,
            "host_id": self.host_id,
            "options": self.options,
            "seats": [
                {
                    "seat": index,
                    "name": seat["name"],
                    "is_bot": seat["is_bot"],
                    "connected": seat["connected"],
                    "player_id": seat["player_id"],
                }
                if seat
                else None
                for index, seat in enumerate(self.seats)
            ],
        }

    def state_for(self, seat: int) -> dict:
        from .main import APP_VERSION

        state = {
            "type": "state",
            "room": self.room_state(),
            "you": seat,
            "version": APP_VERSION,
            "is_host": self.host_id is not None
            and seat >= 0
            and self.seats[seat] is not None
            and self.seats[seat]["player_id"] == self.host_id,
        }
        if self.game is not None:
            state["game"] = self.game.view(seat)
        else:
            state["game"] = None
        return state

    async def broadcast(self) -> None:
        for index, seat in enumerate(self.seats):
            if seat is None:
                continue
            conn = self.connections.get(seat["player_id"])
            if conn is None:
                continue
            await conn.send(self.state_for(index))

    async def notify(self, text: str, level: str = "info") -> None:
        for seat in self.seats:
            if seat is None:
                continue
            conn = self.connections.get(seat["player_id"])
            if conn is None:
                continue
            await conn.send({"type": "notice", "text": text, "level": level})

    # ------------------------------------------------------------------- боты

    def _cancel(self, task: asyncio.Task | None) -> None:
        if task is not None and not task.done():
            task.cancel()

    def schedule_bot(self) -> None:
        self._cancel(self.bot_task)
        self.bot_task = asyncio.create_task(self._bot_turn())

    def _current_is_bot(self) -> bool:
        if self.game is None or self.game.turn is None:
            return False
        seat = self.seats[self.game.turn]
        return bool(seat and seat["is_bot"])

    async def _bot_turn(self) -> None:
        await asyncio.sleep(self.rng.uniform(*BOT_DELAY))
        failed = False
        async with self.lock:
            if self.game is None or self.game.turn is None:
                return
            seat_index = self.game.turn
            seat = self.seats[seat_index]
            if seat is None or not seat["is_bot"]:
                return
            try:
                self._bot_action(seat_index)
            except GameError as exc:
                print(f"[bot] ошибка действия: {exc.code} {exc.message}")
                failed = True
            except Exception as exc:  # noqa: BLE001
                import traceback

                print(f"[bot] непредвиденная ошибка: {exc}")
                traceback.print_exc()
                failed = True
        await self.broadcast()
        if failed:
            # не зацикливаемся на одной и той же ошибке
            self._bot_retries = getattr(self, "_bot_retries", 0) + 1
            if self._bot_retries > 3:
                print("[bot] ход бота застрял, пропускаем")
                self._bot_retries = 0
                return
        else:
            self._bot_retries = 0
        self.after_action()

    def _bot_action(self, seat_index: int) -> None:
        game = self.game
        assert game is not None
        player = game.players[seat_index]
        phase = game.phase

        if phase == PHASE_AUCTION:
            if bot_ai.choose_open(game, seat_index, self.rng):
                # бот открывает карты и продолжает торг как обычно
                game.open_cards(seat_index)
                return
            kind, contract_index = bot_ai.choose_bid(game, seat_index, self.rng)
            blind = not game.players[seat_index].opened
            game.bid(seat_index, kind, contract_index, blind=blind)
        elif phase == PHASE_DROP:
            ids = bot_ai.choose_drop(game, seat_index, self.rng)
            if player.blind or not player.opened:
                ids = [game.token_for(card_id) for card_id in ids]
            game.drop(seat_index, ids)
        elif phase == PHASE_DECLARE:
            index = player.bid if player.bid is not None else 0
            game.declare(seat_index, index, without_three=False)
        elif phase == PHASE_WHIST:
            kind = bot_ai.choose_whist(game, seat_index, self.rng)
            game.whist(seat_index, kind)
        elif phase == PHASE_WHIST_MODE:
            game.whist_mode(seat_index, dark=bot_ai.choose_whist_mode(game, seat_index, self.rng))
        elif phase == PHASE_CATCH_MIZER:
            accept = bot_ai.choose_catch_mizer(game, seat_index, self.rng)
            game.catch_mizer(seat_index, accept)
        elif phase == PHASE_PLAYING:
            card_id = bot_ai.choose_card(game, seat_index, self.rng)
            if player.blind or not player.opened:
                card_id = game.token_for(card_id)
            game.play(seat_index, card_id)

    def after_action(self) -> None:
        """Проверяет, не пора ли передать ход боту или авто-ходить за отключившегося."""
        if self.game is None:
            return
        if self.game.pending:
            # взятка собрана, но ещё показывается игрокам
            self._schedule_resolve()
            return
        if self.game.phase in (PHASE_ROUND_END, PHASE_MATCH_END):
            self._cancel(self.auto_move_task)
            self.auto_move_task = None
            if self.game.phase == PHASE_ROUND_END and self.next_round_task is None:
                self.next_round_task = asyncio.create_task(self._auto_next_round())
            return
        if self._current_is_bot():
            self.schedule_bot()
            return
        if self.game.turn is not None:
            seat = self.seats[self.game.turn]
            if seat is not None and not seat["is_bot"] and not seat["connected"]:
                self._cancel(self.auto_move_task)
                self.auto_move_task = asyncio.create_task(self._auto_move())

    def _schedule_resolve(self) -> None:
        """Откладывает розыгрыш собранной взятки, чтобы её успели увидеть."""
        self._cancel(self.resolve_task)
        self.resolve_task = asyncio.create_task(self._resolve_later())

    async def _resolve_later(self) -> None:
        await asyncio.sleep(TRICK_SHOW_TIME)
        async with self.lock:
            if self.game is not None:
                self.game.resolve_pending()
        await self.broadcast()
        self.after_action()

    async def _auto_next_round(self) -> None:
        await asyncio.sleep(AUTO_NEXT_ROUND_DELAY)
        async with self.lock:
            if self.game is not None and self.game.phase == PHASE_ROUND_END:
                self.game.start_round()
        self.next_round_task = None
        await self.broadcast()
        self.after_action()

    async def _auto_move(self) -> None:
        await asyncio.sleep(AUTO_MOVE_TIMEOUT)
        async with self.lock:
            if self.game is None or self.game.turn is None:
                return
            seat_index = self.game.turn
            seat = self.seats[seat_index]
            if seat is None or seat["is_bot"] or seat["connected"]:
                return
            player = self.game.players[seat_index]
            try:
                if self.game.phase == PHASE_AUCTION:
                    self.game.bid(seat_index, "pass")
                elif self.game.phase == PHASE_DROP:
                    ids = bot_ai.choose_drop(self.game, seat_index, self.rng)
                    if player.blind or not player.opened:
                        ids = [self.game.token_for(card_id) for card_id in ids]
                    self.game.drop(seat_index, ids)
                elif self.game.phase == PHASE_DECLARE:
                    index = player.bid if player.bid is not None else 0
                    self.game.declare(seat_index, index)
                elif self.game.phase == PHASE_WHIST:
                    self.game.whist(seat_index, "pass")
                elif self.game.phase == PHASE_WHIST_MODE:
                    self.game.whist_mode(seat_index, False)
                elif self.game.phase == PHASE_CATCH_MIZER:
                    self.game.catch_mizer(seat_index, False)
                elif self.game.phase == PHASE_PLAYING:
                    legal = self.game.legal_cards(seat_index)
                    if legal:
                        card_id = legal[0].id
                        if player.blind or not player.opened:
                            card_id = self.game.token_for(card_id)
                        self.game.play(seat_index, card_id)
            except GameError:
                pass
        self.auto_move_task = None
        await self.broadcast()
        self.after_action()


class RoomManager:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}
        self.rng = random.Random()

    def new_code(self) -> str:
        while True:
            code = "".join(self.rng.choice(CODE_ALPHABET) for _ in range(5))
            if code not in self.rooms:
                return code

    def create(self, options: dict | None = None) -> Room:
        code = self.new_code()
        room = Room(code, options or {}, self.rng)
        self.rooms[code] = room
        return room

    def get(self, code: str) -> Room | None:
        return self.rooms.get(code.strip().upper())

    def remove(self, code: str) -> None:
        self.rooms.pop(code, None)

    def cleanup(self) -> None:
        for code, room in list(self.rooms.items()):
            if not any(seat and seat["connected"] for seat in room.seats):
                room._cancel(room.bot_task)
                room._cancel(room.next_round_task)
                room._cancel(room.auto_move_task)
                room._cancel(room.resolve_task)
                self.rooms.pop(code, None)
