"""Комнаты: создание, посадка игроков, боты, рассылка состояния."""

from __future__ import annotations

import asyncio
import random
import string
import time
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
AUTO_MOVE_TIMEOUT = 180.0  # 3 минуты на ход; затем за игрока играет бот
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
        self.turn_deadline: float | None = None
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
            game = self.game.view(seat)
            if self.turn_deadline is not None:
                game["turn_deadline"] = round(self.turn_deadline, 3)
                game["turn_time_left"] = max(
                    0, int(round(self.turn_deadline - time.time()))
                )
                game["turn_timeout"] = int(AUTO_MOVE_TIMEOUT)
            state["game"] = game
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
        await self.broadcast()

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

    def _clear_turn_timer(self) -> None:
        self._cancel(self.auto_move_task)
        self.auto_move_task = None
        self.turn_deadline = None

    def after_action(self) -> None:
        """Передаёт ход боту или запускает трёхминутный таймер для человека."""
        if self.game is None:
            self._clear_turn_timer()
            return
        if self.game.pending:
            # взятка собрана, но ещё показывается игрокам
            self._clear_turn_timer()
            self._schedule_resolve()
            return
        if self.game.phase in (PHASE_ROUND_END, PHASE_MATCH_END):
            self._clear_turn_timer()
            if self.game.phase == PHASE_ROUND_END and self.next_round_task is None:
                self.next_round_task = asyncio.create_task(self._auto_next_round())
            return
        if self._current_is_bot():
            self._clear_turn_timer()
            self.schedule_bot()
            return
        if self.game.turn is not None:
            self._schedule_auto_move()

    def _schedule_auto_move(self) -> None:
        """Запускает таймер хода для человека (в том числе отключившегося)."""
        self._clear_turn_timer()
        if self.game is None or self.game.turn is None or self.game.pending:
            return
        seat_index = self.game.turn
        seat = self.seats[seat_index]
        if seat is None or seat["is_bot"]:
            return
        self.turn_deadline = time.time() + AUTO_MOVE_TIMEOUT
        self.auto_move_task = asyncio.create_task(
            self._auto_move(
                seat_index,
                self.game.phase,
                self.game.round_number,
                self.turn_deadline,
            )
        )

    def _schedule_resolve(self) -> None:
        """Откладывает розыгрыш собранной взятки, чтобы её успели увидеть."""
        self._cancel(self.resolve_task)
        self.resolve_task = asyncio.create_task(self._resolve_later())

    async def _resolve_later(self) -> None:
        await asyncio.sleep(TRICK_SHOW_TIME)
        async with self.lock:
            if self.game is not None:
                self.game.resolve_pending()
        self.after_action()
        await self.broadcast()

    async def _auto_next_round(self) -> None:
        await asyncio.sleep(AUTO_NEXT_ROUND_DELAY)
        async with self.lock:
            if self.game is not None and self.game.phase == PHASE_ROUND_END:
                self.game.start_round()
        self.next_round_task = None
        self.after_action()
        await self.broadcast()

    async def _auto_move(
        self,
        seat_index: int,
        phase: str,
        round_number: int,
        deadline: float,
    ) -> None:
        """Ходит за игрока, если он не успел выбрать действие за 3 минуты."""
        await asyncio.sleep(max(0.0, deadline - time.time()))
        timed_out: str | None = None
        async with self.lock:
            if (
                self.game is None
                or self.game.pending
                or self.game.turn != seat_index
                or self.game.phase != phase
                or self.game.round_number != round_number
            ):
                return
            seat = self.seats[seat_index]
            if seat is None or seat["is_bot"]:
                return
            player = self.game.players[seat_index]
            try:
                if phase == PHASE_AUCTION:
                    # Не открываем карты «насовсем» по таймауту: сразу
                    # заявляем доступную ставку (или пас), чтобы ход завершился.
                    kind, contract_index = bot_ai.choose_bid(
                        self.game, seat_index, self.rng
                    )
                    blind = not player.opened
                    self.game.bid(
                        seat_index, kind, contract_index, blind=blind
                    )
                else:
                    self._bot_action(seat_index)
                timed_out = player.name
            except GameError as exc:
                print(f"[timeout] ошибка действия: {exc.code} {exc.message}")
            except Exception as exc:  # noqa: BLE001
                import traceback

                print(f"[timeout] непредвиденная ошибка: {exc}")
                traceback.print_exc()
        self.auto_move_task = None
        self.turn_deadline = None
        if timed_out:
            self.game._log(
                f"Время на ход истекло — за {timed_out} сыграл бот."
            )
        self.after_action()
        await self.broadcast()
        if timed_out:
            await self.notify(
                f"Время на ход истекло — за {timed_out} сыграл бот.",
                "info",
            )


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
