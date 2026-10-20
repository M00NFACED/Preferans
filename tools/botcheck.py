"""Проверка качества игры бота: оценка руки против реально взятых взяток."""

from __future__ import annotations

import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bot as bot_ai  # noqa: E402
from app.game import (  # noqa: E402
    Game,
    Player,
    PHASE_AUCTION,
    PHASE_CATCH_MIZER,
    PHASE_DECLARE,
    PHASE_DROP,
    PHASE_MATCH_END,
    PHASE_PLAYING,
    PHASE_ROUND_END,
    PHASE_WHIST,
)


def run(seed: int, samples: list[tuple[float, int]]) -> None:
    rng = random.Random(seed)
    players = [Player(seat=i, pid=str(i), name=f"P{i}", is_bot=True) for i in range(3)]
    game = Game(players, max_bullet=30, seed=seed)
    game.start_round()
    est_at_bid: dict[int, float] = {}
    guard = 0
    while game.phase != PHASE_MATCH_END and guard < 20000:
        guard += 1
        seat = game.turn
        if seat is None:
            if game.phase == PHASE_ROUND_END:
                for entry in game.round_history:
                    if entry["type"] != "contract":
                        continue
                    d = entry["declarer"]
                    if d in est_at_bid:
                        samples.append((est_at_bid[d], entry["tricks"][d]))
                est_at_bid = {}
                game.start_round()
                continue
            break
        if game.phase == PHASE_AUCTION:
            kind, index = bot_ai.choose_bid(game, seat, rng)
            if kind == "contract":
                hand = game.players[seat].hand
                est_at_bid[seat] = max(bot_ai.estimate_tricks(hand, s) for s in range(4))
            game.bid(seat, kind, index)
        elif game.phase == PHASE_DROP:
            game.drop(seat, bot_ai.choose_drop(game, seat, rng))
        elif game.phase == PHASE_DECLARE:
            p = game.players[seat]
            game.declare(seat, p.bid if p.bid is not None else 0)
        elif game.phase == PHASE_WHIST:
            game.whist(seat, bot_ai.choose_whist(game, seat, rng))
        elif game.phase == PHASE_CATCH_MIZER:
            game.catch_mizer(seat, bot_ai.choose_catch_mizer(game, seat, rng))
        elif game.phase == PHASE_PLAYING:
            game.play(seat, bot_ai.choose_card(game, seat, rng))
            if game.pending:
                game.resolve_pending()


def main() -> int:
    samples: list[tuple[float, int]] = []
    for seed in range(int(sys.argv[1]) if len(sys.argv) > 1 else 20):
        run(seed, samples)
    buckets: dict[tuple[float, float], list[int]] = defaultdict(list)
    for est, actual in samples:
        key = (int(est * 2) / 2, int(est * 2) / 2 + 0.5)
        buckets[key].append(actual)
    print(f"выборок: {len(samples)}")
    for key in sorted(buckets):
        values = buckets[key]
        if len(values) >= 3:
            print(
                f"  est {key[0]:.1f}-{key[1]:.1f}: n={len(values):<4} среднее взято {sum(values)/len(values):.2f}"
            )
    overall = sum(a for _e, a in samples) / max(1, len(samples))
    print("среднее взято:", round(overall, 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
