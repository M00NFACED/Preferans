"""Тест слепой игры: слепая заявка, удвоение ставок, режим виста вслепую.

Запуск:  python tools/e2e_blind.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("  [ok] " if condition else "  [FAIL] ") + message)
    if not condition:
        FAILURES.append(message)


class Session:
    def __init__(self, client: TestClient, name: str):
        self.client = client
        self.name = name
        self.state = None
        self.errors = []

    def __enter__(self):
        self.ws = self.client.websocket_connect("/ws")
        self.ws.__enter__()
        return self

    def __exit__(self, *args):
        self.ws.__exit__(*args)

    def send(self, payload: dict) -> None:
        self.ws.send_json(payload)

    def pump(self) -> dict:
        message = self.ws.receive_json()
        if message.get("type") == "state":
            self.state = message
        elif message.get("type") == "error":
            self.errors.append(message)
            print("   ОШИБКА СЕРВЕРА:", message.get("code"), message.get("message"))
        else:
            print("   сообщение:", message.get("type"))
        return message

    def wait_for(self, predicate, timeout_states: int = 40) -> dict:
        for _ in range(timeout_states):
            message = self.pump()
            if message.get("type") == "state" and predicate(message):
                return message
        return self.state or {}


def main() -> int:
    with TestClient(app) as client:
        with Session(client, "Слепой") as session:
            session.send({"type": "create", "name": "Слепой", "player_id": "blind",
                          "options": {"variant": 1, "max_bullet": 30, "blind": True}})
            message = session.wait_for(lambda m: m.get("game") is None)
            check(bool(message.get("room")), "комната создана")
            check(message["room"]["options"]["blind"] is True, "опция «слепая игра» включена")

            session.send({"type": "add_bot"})
            session.wait_for(lambda m: m.get("room") and
                             sum(1 for s in m["room"]["seats"] if s) == 2)
            session.send({"type": "add_bot"})
            session.wait_for(lambda m: m.get("room") and
                             sum(1 for s in m["room"]["seats"] if s) == 3)
            session.send({"type": "start"})
            message = session.wait_for(lambda m: m.get("game") is not None)
            game = message["game"]
            check(game["phase"] == "auction", "идёт торг")
            check(game.get("can_bid_blind") is True, "слепая заявка доступна")

            # максимальная слепая заявка: боты уже не смогут её перебить
            session.send({"type": "bid", "kind": "contract", "contract": 24, "blind": True})
            message = session.wait_for(lambda m: m.get("game") and m["game"]["phase"] == "auction")
            game = message["game"]
            check(game["current_bid"] == 24, "заявка принята как 10 б/к")
            check(game.get("blind_bidder") is not None,
                  "заявка отмечена как слепая (blind_bidder)")
            check(all("suit" not in c for c in (game.get("hand") or []) if c.get("blind")),
                  "закрытые карты не раскрывают масть и ранг")
            available = game.get("available_bids") or []
            check(not available, "максимальную заявку перебить нечем")

            # играем раунд до конца
            checked_drop = False
            checked_after_drop = False
            for step in range(200):
                message = session.pump()
                if message.get("type") == "error":
                    print("   ошибка:", message)
                    continue
                if message.get("type") != "state":
                    continue
                game = message.get("game")
                if not game:
                    continue
                print(f"   [{step}] {game['phase']} ход={game.get('turn')} "
                      f"blind={game.get('blind')} слепой_заказчик={game.get('blind_declarer')} "
                      f"взятка={len(game.get('trick') or [])} pending={game.get('pending')}")
                if game["phase"] in ("round_end", "match_end"):
                    break
                if checked_drop and not checked_after_drop and game["phase"] in ("declare", "whist"):
                    check(len(game.get("hand") or []) == 10, "после сноса осталось 10 карт")
                    check(not game.get("talon"), "после сноса прикуп больше не показывается")
                    checked_after_drop = True
                if game.get("turn") != message.get("you"):
                    continue
                phase = game["phase"]
                if phase == "auction":
                    available = game.get("available_bids") or []
                    if available:
                        session.send({"type": "bid", "kind": "contract", "contract": available[0]})
                    else:
                        session.send({"type": "bid", "kind": "pass"})
                elif phase == "drop":
                    hand = game.get("hand") or []
                    hand_ids = [c["id"] for c in hand]
                    talon_ids = [c["id"] for c in (game.get("talon") or [])]
                    if not checked_drop:
                        check(game.get("blind") is False,
                              "после торга карты заказчика открыты")
                        check(game.get("opened") is True,
                              "после торга заказчик видит свою руку")
                        check(len(hand_ids) == 12,
                              "на сносе 12 карт (10 + прикуп)")
                        check(all("suit" in c for c in hand),
                              "карты в руке открыты, а не токены")
                        check(set(talon_ids) <= set(hand_ids),
                              "прикуп добавлен в руку до сноса")
                        checked_drop = True
                    ids = [c["id"] for c in hand[:2]]
                    if talon_ids:
                        other = next((cid for cid in hand_ids if cid != talon_ids[0]), None)
                        if other is not None:
                            ids = [talon_ids[0], other]
                    session.send({"type": "drop", "cards": ids})
                elif phase == "declare":
                    session.send({"type": "declare", "contract": game.get("current_bid") or 0})
                elif phase == "whist":
                    session.send({"type": "whist", "kind": "pass"})
                elif phase == "whist_mode":
                    session.send({"type": "whist_mode", "dark": True})
                elif phase == "catch_mizer":
                    session.send({"type": "catch_mizer", "accept": False})
                elif phase == "playing":
                    if game.get("pending"):
                        continue
                    legal = game.get("legal") or []
                    if legal:
                        session.send({"type": "play", "card": legal[0]})

            game = session.state["game"]
            check(game["phase"] in ("round_end", "match_end"), "раунд доигран")
            check(game.get("blind_declarer") is True, "заявка была слепой (blind_declarer)")
            check(game.get("blind") is False, "после торга заказчик играл с открытыми картами")
            check(checked_drop, "снос заказчика был в тесте")
            result = game.get("last_result") or {}
            check("вслепую" in (result.get("contract") or "").lower(),
                  "в итогах отмечено «вслепую»")
            if result.get("made") is True:
                tricks = (game.get("contract") or {}).get("tricks", 0)
                expected = min(game["max_bullet"], (tricks - 5) * 2 * 2)
                actual = game["players"][game["you"]]["bullet"]
                check(actual == expected,
                      f"слепая премия удвоена: {actual} (ожидалось {expected})")
            check(not session.errors, "ошибок нет: " + str(session.errors))

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
