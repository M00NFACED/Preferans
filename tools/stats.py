"""Разбор настроек: статистика типов раундов, точность бота, длительность матча."""

from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import rules as R  # noqa: E402
from tools.simulate import play_match  # noqa: E402


def main() -> int:
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    bullet = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    types: collections.Counter = collections.Counter()
    deltas: collections.Counter = collections.Counter()
    contract_counts: collections.Counter = collections.Counter()
    made = 0
    total = 0
    rounds: list[int] = []
    for variant in (R.VARIANT_SOCHI, R.VARIANT_LENINGRAD):
        for seed in range(seeds):
            game = play_match(variant, bullet, seed)
            types.update(game.round_types)
            rounds.append(game.round_number)
            for entry in game.round_history:
                if entry["type"] != "contract":
                    continue
                need = int(entry["contract"].split()[0])
                taken = entry["tricks"][entry["declarer"]]
                deltas[taken - need] += 1
                contract_counts[need] += 1
                total += 1
                made += 1 if taken >= need else 0
    total_all = sum(types.values())
    print("типы раундов:", {k: f"{v} ({round(100 * v / total_all)}%)" for k, v in types.items()})
    if total:
        print("контракты по количеству взяток:", dict(sorted(contract_counts.items())))
        print("дельта (взято - надо):", sorted(deltas.items()))
        print(f"контрактов выполнено: {made}/{total} = {round(100 * made / total)}%")
    print(
        "длина матча: мин",
        min(rounds),
        "макс",
        max(rounds),
        "сред",
        round(sum(rounds) / len(rounds), 1),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
