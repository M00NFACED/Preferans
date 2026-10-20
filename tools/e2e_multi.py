"""Сквозной тест на несколько живых игроков (нужен запущенный сервер).

Запуск:  python tools/e2e_multi.py [ws://127.0.0.1:8030/ws]
"""

from __future__ import annotations

import asyncio
import json
import sys

import websockets

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("  [ok] " if condition else "  [FAIL] ") + message)
    if not condition:
        FAILURES.append(message)


class Player:
    def __init__(self, name: str):
        self.name = name
        self.state = None
        self.errors = []

    async def connect(self, url: str) -> None:
        self.ws = await websockets.connect(url)
        self.reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                message = json.loads(raw)
                if message.get("type") == "state":
                    self.state = message
                elif message.get("type") == "error":
                    self.errors.append(message)
        except Exception:
            pass

    async def send(self, payload: dict) -> None:
        await self.ws.send(json.dumps(payload))

    async def wait(self, predicate, timeout: float = 25.0) -> bool:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if self.state and predicate(self.state):
                return True
            await asyncio.sleep(0.15)
        return False

    async def close(self) -> None:
        self.reader.cancel()
        await self.ws.close()


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8030/ws"
    a = Player("Аня")
    b = Player("Борис")
    await a.connect(url)
    await b.connect(url)

    await a.send({"type": "create", "name": "Аня", "player_id": "anya",
                  "options": {"variant": 1, "max_bullet": 15}})
    ok = await a.wait(lambda s: s.get("game") is None and s["room"]["code"])
    check(ok, "комната создана")
    code = a.state["room"]["code"]
    print("       код комнаты:", code)

    await b.send({"type": "join", "code": code, "name": "Борис", "player_id": "boris"})
    ok = await a.wait(lambda s: sum(1 for x in s["room"]["seats"] if x) == 2)
    check(ok, "второй игрок подключился")

    await a.send({"type": "add_bot"})
    ok = await a.wait(lambda s: sum(1 for x in s["room"]["seats"] if x) == 3)
    check(ok, "бот добавлен")

    await a.send({"type": "start"})
    ok = await a.wait(lambda s: s.get("game") is not None)
    check(ok, "игра началась")
    check(ok and a.state["game"]["phase"] == "auction", "идёт торг")

    # каждый по очереди пасует / называет контракт
    for step in range(150):
        game = a.state["game"]
        if game["phase"] in ("round_end", "match_end"):
            break
        seat = game.get("turn")
        player = a if seat == a.state["you"] else b if seat == b.state["you"] else None
        if player is None:
            await asyncio.sleep(0.3)
            continue
        game = player.state["game"]  # у каждого своя рука
        phase = game["phase"]
        if phase == "auction":
            if game.get("can_open"):
                await player.send({"type": "open_cards"})
                await asyncio.sleep(0.3)
                continue
            if game.get("current_bid") is None:
                available = game.get("available_bids") or []
                if available:
                    await player.send({"type": "bid", "kind": "contract", "contract": available[0]})
                else:
                    await player.send({"type": "bid", "kind": "pass"})
            else:
                await player.send({"type": "bid", "kind": "pass"})
        elif phase == "drop":
            hand = game.get("hand") or []
            await player.send({"type": "drop", "cards": [c["id"] for c in hand[:2]]})
        elif phase == "declare":
            await player.send({"type": "declare", "contract": game.get("current_bid") or 0,
                               "without_three": False})
        elif phase == "whist":
            await player.send({"type": "whist", "kind": "pass"})
        elif phase == "catch_mizer":
            await player.send({"type": "catch_mizer", "accept": False})
        elif phase == "playing":
            if game.get("pending"):
                await asyncio.sleep(0.4)
                continue
            legal = game.get("legal") or []
            if legal:
                await player.send({"type": "play", "card": legal[0]})
        await asyncio.sleep(0.4)

    game = a.state["game"]
    check(game["phase"] in ("round_end", "match_end"), f"раунд доигран (фаза {game['phase']})")
    check(sum(p["tricks"] for p in game["players"]) == 10, "розыграно 10 взяток")
    check(not a.errors and not b.errors, f"ошибок нет: {a.errors + b.errors}")

    # оба видят одинаковую таблицу очков
    check(
        [p["vists"] for p in a.state["game"]["players"]]
        == [p["vists"] for p in b.state["game"]["players"]],
        "оба игрока видят одинаковые очки",
    )

    await a.close()
    await b.close()

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
