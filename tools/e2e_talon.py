"""Проверка механики прикупа: раскрыт на сносе, снос двух карт из десяти,
прикуп уходит в руку только после сноса."""

from __future__ import annotations

import asyncio
import json
import sys

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8090/ws"
FAILURES = []


def check(condition, message):
    print(("  [ok] " if condition else "  [FAIL] ") + message)
    if not condition:
        FAILURES.append(message)


class Client:
    def __init__(self, name):
        self.name = name
        self.state = None
        self.ws = None

    async def connect(self):
        self.ws = await websockets.connect(URL)
        self.task = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for raw in self.ws:
                message = json.loads(raw)
                if message.get("type") == "state":
                    self.state = message
        except Exception:
            pass

    async def send(self, payload):
        await self.ws.send(json.dumps(payload))

    async def wait(self, predicate, timeout=25.0):
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if self.state and predicate(self.state):
                return self.state
            await asyncio.sleep(0.1)
        return self.state


async def main():
    human = Client("Аня")
    await human.connect()
    await human.send({"type": "create", "name": "Аня", "player_id": "anya",
                      "options": {"variant": 1, "max_bullet": 30, "blind": False}})
    await human.wait(lambda s: s.get("game") is None and s.get("room"))
    await human.send({"type": "add_bot"})
    await asyncio.sleep(0.3)
    await human.send({"type": "add_bot"})
    await asyncio.sleep(0.3)
    await human.send({"type": "start"})

    # торг: открываем карты и заявляем контракт
    for _ in range(40):
        await asyncio.sleep(0.4)
        game = human.state["game"]
        if game["phase"] != "auction":
            break
        if game.get("turn") == human.state["you"]:
            if game.get("can_open"):
                await human.send({"type": "open_cards"})
            else:
                available = game.get("available_bids") or []
                if available:
                    # максимальная заявка, чтобы заказчиком точно стал человек
                    await human.send({"type": "bid", "kind": "contract", "contract": available[-1]})
                else:
                    await human.send({"type": "bid", "kind": "pass"})

    game = human.state["game"]
    check(game["phase"] == "drop", "дошли до этапа сноса (фаза " + game["phase"] + ")")
    if game["phase"] != "drop":
        return 1

    talon_ids = [c["id"] for c in game.get("talon") or []]
    hand_ids = [c["id"] for c in game.get("hand") or []]
    check(len(talon_ids) == 2, "прикуп раскрыт и виден всем на сносе")
    check(len(hand_ids) == 12, "у заказчика 12 карт на сносе (10 + прикуп)")
    check(set(talon_ids) <= set(hand_ids), "прикуп уже добавлен в руку заказчика")

    # сносим карту прикупа и ещё одну карту с руки
    other_id = next(cid for cid in hand_ids if cid not in talon_ids)
    dropped_talon = talon_ids[0]
    await human.send({"type": "drop", "cards": [dropped_talon, other_id]})
    await human.wait(lambda s: s["game"]["phase"] in ("declare", "whist"))
    game = human.state["game"]
    check(len(game.get("hand") or []) == 10, "после сноса осталось 10 карт")
    check(len(game.get("talon") or []) == 0, "после сноса прикуп больше не показывается")
    check(all(c["id"] != dropped_talon for c in game.get("hand") or []),
          "карту прикупа можно сбросить")
    check(game["phase"] == "declare", "перешли к назначению контракта")

    await human.ws.close()
    print()
    if FAILURES:
        print("ПРОВАЛЕНО:", len(FAILURES))
        return 1
    print("Все проверки пройдены.")
    return 0


raise SystemExit(asyncio.run(main()))
