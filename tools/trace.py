"""Покадровый разбор одной партии — для отладки игры бота."""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bot as bot_ai  # noqa: E402
from app import cards as C  # noqa: E402
from app import rules as R  # noqa: E402
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


def card_text(card) -> str:
    return f"{C.SUIT_SYMBOL[card.suit]}{card.label}"


def main() -> int:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    rng = random.Random(seed)
    players = [Player(seat=i, pid=str(i), name=f"P{i}", is_bot=True) for i in range(3)]
    game = Game(players, max_bullet=30, seed=seed)
    game.start_round()
    guard = 0
    while game.phase != PHASE_MATCH_END and guard < 4000:
        guard += 1
        seat = game.turn
        if seat is None:
            if game.phase == PHASE_ROUND_END:
                print("--- раунд завершён:", game.last_result)
                game.start_round()
                continue
            break
        if game.phase == PHASE_AUCTION:
            kind, index = bot_ai.choose_bid(game, seat, rng)
            print(f"торг: P{seat} -> {kind} {R.contract_name(index) if index is not None else ''}")
            game.bid(seat, kind, index)
        elif game.phase == PHASE_DROP:
            ids = bot_ai.choose_drop(game, seat, rng)
            print(f"снос: P{seat} сбрасывает {[card_text(c) for c in game.players[seat].hand if c.id in ids]}")
            game.drop(seat, ids)
        elif game.phase == PHASE_DECLARE:
            p = game.players[seat]
            idx = p.bid if p.bid is not None else 0
            print(f"контракт: P{seat} -> {R.contract_name(idx)}")
            game.declare(seat, idx)
        elif game.phase == PHASE_WHIST:
            kind = bot_ai.choose_whist(game, seat, rng)
            print(f"вист: P{seat} -> {kind}")
            game.whist(seat, kind)
        elif game.phase == PHASE_CATCH_MIZER:
            accept = bot_ai.choose_catch_mizer(game, seat, rng)
            game.catch_mizer(seat, accept)
        elif game.phase == PHASE_PLAYING:
            legal = game.legal_cards(seat)
            card = bot_ai.choose_card(game, seat, rng)
            chosen = next(c for c in legal if c.id == card)
            trick = " ".join(card_text(c) for _s, c in game.trick)
            hand = " ".join(card_text(c) for c in sorted(game.players[seat].hand, key=lambda c: (c.suit, -c.rank)))
            print(
                f"ход: P{seat} кладёт {card_text(chosen)} | взятка: {trick or '-'} | "
                f"рука: {hand} | козырь: {C.SUIT_SYMBOL.get(game.trump()) if game.trump() is not None else '-'}"
            )
            game.play(seat, card)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
