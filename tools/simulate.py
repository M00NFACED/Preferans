"""Автономный прогон: трое ботов играют полный матч без сети.

Запуск:  python tools/simulate.py [матчей] [--variant 1|2] [--bullet 10]
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bot as bot_ai  # noqa: E402
from app import rules as R  # noqa: E402
from app.game import (  # noqa: E402
    Game,
    GameError,
    PHASE_AUCTION,
    PHASE_CATCH_MIZER,
    PHASE_DECLARE,
    PHASE_DROP,
    PHASE_MATCH_END,
    PHASE_PLAYING,
    PHASE_ROUND_END,
    PHASE_WHIST,
    Player,
)


def play_match(variant: int, max_bullet: int, seed: int) -> Game:
    rng = random.Random(seed)
    players = [
        Player(seat=i, pid=f"bot-{i}", name=f"Бот {i + 1}", is_bot=True) for i in range(3)
    ]
    game = Game(players, variant=variant, max_bullet=max_bullet, seed=seed)
    game.start_round()
    guard = 0
    while game.phase != PHASE_MATCH_END and guard < 20000:
        guard += 1
        seat = game.turn
        if seat is None:
            if game.phase == PHASE_ROUND_END:
                game.start_round()
                continue
            break
        try:
            if game.phase == PHASE_AUCTION:
                kind, index = bot_ai.choose_bid(game, seat, rng)
                game.bid(seat, kind, index)
            elif game.phase == PHASE_DROP:
                game.drop(seat, bot_ai.choose_drop(game, seat, rng))
            elif game.phase == PHASE_DECLARE:
                player = game.players[seat]
                index = player.bid if player.bid is not None else 0
                game.declare(seat, index)
            elif game.phase == PHASE_WHIST:
                game.whist(seat, bot_ai.choose_whist(game, seat, rng))
            elif game.phase == PHASE_CATCH_MIZER:
                game.catch_mizer(seat, bot_ai.choose_catch_mizer(game, seat, rng))
            elif game.phase == PHASE_PLAYING:
                game.play(seat, bot_ai.choose_card(game, seat, rng))
                if game.pending:
                    game.resolve_pending()
            elif game.phase == PHASE_ROUND_END:
                game.start_round()
        except GameError as exc:
            print(f"ОШИБКА: {exc.code} {exc.message} (фаза {game.phase}, ход {seat})")
            raise
    return game


def main() -> int:
    matches = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3
    variant = R.VARIANT_SOCHI
    max_bullet = 10
    if "--variant" in sys.argv:
        variant = int(sys.argv[sys.argv.index("--variant") + 1])
    if "--bullet" in sys.argv:
        max_bullet = int(sys.argv[sys.argv.index("--bullet") + 1])

    for seed in range(matches):
        game = play_match(variant, max_bullet, seed)
        print("=" * 60)
        print(f"Матч {seed + 1}: вариант {R.VARIANT_NAMES[variant]}, пуля {max_bullet}, "
              f"раундов {game.round_number}")
        for p in game.players:
            print(f"  {p.name}: взяток суммарно {sum(1 for _ in p.trick_taken)}, "
                  f"пуля {p.bullet}, гора {p.mountain}, висты {p.vists}")
        winner = max(game.players, key=lambda p: p.vists)
        print(f"  Победитель: {winner.name} ({winner.vists} вистов)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
