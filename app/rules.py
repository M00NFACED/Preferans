"""Правила: лестница контрактов, мизер, вист/полвиста, распасы и расчёт очков.

Контракты (25 штук) идут лестницей по старшинству:

    6 пик → 6 треф → 6 бубн → 6 червей → 6 без козыря → 7 пик → ... → 10 без козыря

Козырь — это масть контракта. Отдельно объявляется «Мизер» (не взять ни одной взятки).
"""

from __future__ import annotations

from dataclasses import dataclass

from .cards import HEARTS, NO_TRUMP, SUIT_SHORT

MIN_TRICKS = 6
MAX_TRICKS = 10
TRUMP_CHOICES = (0, 1, 2, 3, NO_TRUMP)  # ♠ ♣ ♦ ♥ без козыря

VIST_PER_BULLET = 10   # одно очко в пуле = 10 вистов
VIST_PER_MOUNTAIN = 7  # одно очко в горе = 7 вистов
MOUNTAIN_TO_BULLET_NUM = VIST_PER_MOUNTAIN   # очко горы -> 0,7 очка в пули соперников
MOUNTAIN_TO_BULLET_DEN = 10
BULLET_LENGTHS = (5, 10, 15, 30, 50)  # допустимые длины пули (README)
CATCH_MIZER_BONUS = 10        # ставка «ловить мизер»

VARIANT_SOCHI = 1
VARIANT_LENINGRAD = 2
VARIANT_NAMES = {VARIANT_SOCHI: "Сочи", VARIANT_LENINGRAD: "Ленинград"}


@dataclass(frozen=True)
class Contract:
    index: int
    tricks: int
    trump: int

    @property
    def name(self) -> str:
        if self.trump == NO_TRUMP:
            return f"{self.tricks} без козыря"
        return f"{self.tricks} {SUIT_SHORT[self.trump]}"

    @property
    def short(self) -> str:
        return f"{self.tricks}{'♠♣♦♥'[self.trump] if self.trump != NO_TRUMP else 'б/к'}"

    def to_dict(self) -> dict:
        return {"index": self.index, "tricks": self.tricks, "trump": self.trump, "name": self.name}


def build_contracts() -> list[Contract]:
    contracts: list[Contract] = []
    idx = 0
    for tricks in range(MIN_TRICKS, MAX_TRICKS + 1):
        for trump in TRUMP_CHOICES:
            contracts.append(Contract(index=idx, tricks=tricks, trump=trump))
            idx += 1
    return contracts


CONTRACTS = build_contracts()
CONTRACT_COUNT = len(CONTRACTS)


def contract(index: int) -> Contract:
    return CONTRACTS[index]


def contract_name(index: int) -> str:
    return CONTRACTS[index].name


def contract_from(tricks: int, trump: int) -> Contract:
    return CONTRACTS[(tricks - MIN_TRICKS) * len(TRUMP_CHOICES) + TRUMP_CHOICES.index(trump)]


def bullet_premium(tricks: int) -> int:
    """Сколько очков пишется в свою пулю за сыгранный контракт: (N-5)*2."""
    return (tricks - 5) * 2


def mountain_per_trick(tricks: int, variant: int) -> int:
    """Штраф в гору за каждую недобранную взятку."""
    return bullet_premium(tricks) * variant


MIZER_BULLET = 10          # премия в пулю за сыгранный мизер
MIZER_MOUNTAIN_PER_TRICK = 10  # штраф в гору за каждую взятую взятку в мизере

# контракт -> (сколько взяток должен взять вистующий, премия вистов)
WHIST_TABLE = {
    6: (4, 8),
    7: (2, 8),
    8: (1, 6),
    9: (1, 8),
    10: (1, 10),
}
# полвиста доступен только для контрактов 6 и 7
HALF_WHIST_CONTRACTS = (6, 7)

# «без 3 взяток» — дополнительное обещание контрактующего: взять меньше трёх взяток
WITHOUT_THREE_BULLET = 2
WITHOUT_THREE_MOUNTAIN_FACTOR = 1


def whist_requirement(tricks: int, half: bool) -> int:
    need, _reward = WHIST_TABLE[tricks]
    if half and tricks in HALF_WHIST_CONTRACTS:
        return need // 2
    return need


def whist_reward(tricks: int, half: bool) -> int:
    """Висты за взятый вист.

    Множитель варианта здесь не применяется: в «Ленинграде» удваивается
    только гора за недобор контракта (README).
    """
    _need, reward = WHIST_TABLE[tricks]
    if half and tricks in HALF_WHIST_CONTRACTS:
        reward = reward // 2
    return reward


def split_points(total: int, count: int, start: int = 0) -> list[int]:
    """Разложить total очков поровну между count получателями.

    Остаток распределяется по кругу, начиная с позиции start, чтобы
    при повторных расчётах он не доставался всегда первому получателю.
    """
    if count <= 0:
        return []
    base = total // count
    rest = total - base * count
    return [
        base + (1 if 0 <= (i - start) % count < rest else 0)
        for i in range(count)
    ]
