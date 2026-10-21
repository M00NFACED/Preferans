"""Проверка таймера хода: по истечении времени за человека играет бот.

Для теста трёхминутный таймер временно уменьшается до долей секунды.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import rooms  # noqa: E402
from app.main import app  # noqa: E402

rooms.AUTO_MOVE_TIMEOUT = 0.4
FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("  [ok] " if condition else "  [FAIL] ") + message)
    if not condition:
        FAILURES.append(message)


class Session:
    def __init__(self, client: TestClient, name: str):
        self.client = client
        self.name = name

    def __enter__(self):
        self.ws = self.client.websocket_connect("/ws")
        self.ws.__enter__()
        return self

    def __exit__(self, *args):
        self.ws.__exit__(*args)

    def send(self, payload: dict) -> None:
        self.ws.send_json(payload)

    def wait_for(self, predicate, attempts: int = 80) -> dict:
        for _ in range(attempts):
            message = self.ws.receive_json()
            if predicate(message):
                return message
        raise AssertionError("не дождались нужного состояния")


def main() -> int:
    print("Проверка таймера хода")
    with TestClient(app) as client:
        with Session(client, "Тест") as session:
            session.send({
                "type": "create",
                "name": "Тест",
                "player_id": "timeout-player",
                "options": {"variant": 1, "max_bullet": 30, "blind": False},
            })
            state = session.wait_for(lambda m: m.get("type") == "state" and m.get("room"))
            check(bool(state["room"]["code"]), "комната создана")

            session.send({"type": "add_bot"})
            session.send({"type": "add_bot"})
            session.send({"type": "start"})

            started = session.wait_for(
                lambda m: m.get("game") and m["game"].get("phase") == "auction"
                and m["game"].get("turn") == 0
            )
            game = started["game"]
            check(game.get("turn_time_left") is not None,
                  "клиент получает оставшееся время хода")

            seen = None
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                message = session.ws.receive_json()
                game = message.get("game") or {}
                if any("Время на ход истекло" in line for line in game.get("log", [])):
                    seen = message
                    break

            check(seen is not None, "по таймауту бот сделал ход за игрока")
            if seen:
                check(any("Время на ход истекло" in line for line in seen["game"]["log"]),
                      "в журнале есть сообщение о таймауте")

    if FAILURES:
        print("Провалено проверок:", len(FAILURES))
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
