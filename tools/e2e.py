"""Сквозной тест без сети: клиент (TestClient) проходит раунд с двумя ботами.

Проверяется весь цикл: лобби -> торг -> прикуп/снос -> контракт -> вист -> взятки ->
итог раунда -> следующий раунд, а также переподключение (resume) и корректность очков.

Запуск:  python tools/e2e.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  [ok] {message}")
    else:
        print(f"  [FAIL] {message}")
        FAILURES.append(message)


class Session:
    """Упрощённый клиент поверх WebSocket TestClient."""

    def __init__(self, client: TestClient, name: str):
        self.client = client
        self.name = name
        self.state = None
        self.seat = -1
        self.errors = []

    def __enter__(self):
        self.ws = self.client.websocket_connect("/ws")
        self.ws.__enter__()
        return self

    def __exit__(self, *args):
        self.ws.__exit__(*args)

    def send(self, payload: dict) -> None:
        self.ws.send_json(payload)

    def pump(self, timeout: float = 5.0) -> dict:
        message = self.ws.receive_json()
        if message.get("type") == "state":
            self.state = message
            self.seat = message["you"]
        elif message.get("type") == "error":
            self.errors.append(message)
        return message

    def play_round(self) -> bool:
        """Играет раунд, пока не придёт round_end/match_end. True — раунд завершён."""
        while True:
            message = self.pump()
            if message.get("type") == "error":
                continue
            if message.get("type") != "state":
                continue
            game = message.get("game")
            if not game:
                continue
            if game["phase"] in ("round_end", "match_end"):
                return game["phase"] == "round_end"
            if game.get("turn") != self.seat:
                continue
            phase = game["phase"]
            if phase == "auction":
                if game.get("can_open"):
                    self.send({"type": "open_cards"})
                    continue
                available = game.get("available_bids") or []
                if available:
                    self.send({"type": "bid", "kind": "contract", "contract": available[0]})
                else:
                    self.send({"type": "bid", "kind": "pass"})
            elif phase == "drop":
                hand = game.get("hand") or []
                self.send({"type": "drop", "cards": [c["id"] for c in hand[:2]]})
            elif phase == "declare":
                self.send({"type": "declare", "contract": game.get("current_bid") or 0,
                           "without_three": False})
            elif phase == "whist":
                self.send({"type": "whist", "kind": "pass"})
            elif phase == "catch_mizer":
                self.send({"type": "catch_mizer", "accept": False})
            elif phase == "playing":
                if game.get("pending"):
                    continue
                legal = game.get("legal") or []
                if legal:
                    self.send({"type": "play", "card": legal[0]})


def main() -> int:
    with TestClient(app) as client:
        # --- лобби
        with Session(client, "Тестер") as session:
            session.send({"type": "create", "name": "Тестер", "player_id": "tester",
                          "options": {"variant": 1, "max_bullet": 30}})
            room_code = None
            for _ in range(6):
                message = session.pump()
                if message.get("type") == "joined":
                    room_code = message["room"]
                if message.get("type") == "state" and message.get("game") is None:
                    break
            check(bool(room_code), "комната создана, код " + str(room_code))

            session.send({"type": "add_bot"})
            session.pump()
            session.send({"type": "add_bot"})
            session.pump()
            session.send({"type": "start"})

            finished = session.play_round()
            check(finished, "раунд доигран до конца")
            game = session.state["game"]
            check(not session.errors, "ошибок от сервера нет: " + str(session.errors))
            check(game["phase"] == "round_end", "фаза после раунда: " + game["phase"])
            check(sum(p["tricks"] for p in game["players"]) == 10,
                  "розыграно 10 взяток")
            check(all(0 <= p["bullet"] <= game["max_bullet"] for p in game["players"]),
                  "пуля в пределах лимита")
            check(all(p["vists"] >= -10_000 for p in game["players"]),
                  "висты в разумных пределах")
            result = game.get("last_result") or {}
            check(bool(result.get("lines")), "итог раунда содержит пояснения")

            # --- переподключение
            session.send({"type": "next_round"})
            for _ in range(6):
                message = session.pump()
                if message.get("type") == "state" and message.get("game"):
                    if message["game"]["phase"] == "auction":
                        break

        # переподключаемся в ту же комнату
        with Session(client, "Тестер") as again:
            again.send({"type": "resume", "code": room_code, "player_id": "tester"})
            resumed = False
            for _ in range(6):
                message = again.pump()
                if message.get("type") == "state" and message.get("game"):
                    resumed = True
                    break
            check(resumed, "переподключение к комнате работает")

            # --- играем ещё раунд после переподключения
            finished = again.play_round()
            check(finished, "раунд после переподключения доигран")

        # --- неверный код комнаты
        with Session(client, "Прохожий") as stranger:
            stranger.send({"type": "join", "code": "ZZZZZ", "name": "Прохожий",
                           "player_id": "stranger"})
            got_error = False
            for _ in range(4):
                message = stranger.pump()
                if message.get("type") == "error":
                    got_error = True
                    break
            check(got_error, "вход по неверному коду даёт понятную ошибку")

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО проверок: {len(FAILURES)}")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
