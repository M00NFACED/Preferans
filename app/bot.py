"""Бот: решает заявки, сброс карт, вист и ход картой.

Оценка руки намеренно простая — бот играет «нормально», а не оптимально,
поэтому его можно обыграть, но он не делает откровенных глупостей.
"""

from __future__ import annotations

import random

from . import cards as C
from . import rules as R
from .game import Game, Player, ROUND_CONTRACT, ROUND_MIZER, ROUND_RASPAS

BOT_NAMES = [
    "Бот", "Скай", "Компьютер", "Машина", "Автомат",
    "Робот", "Калькулятор", "Алгоритм", "Сервер", "ИИ",
]


def random_name(rng: random.Random) -> str:
    return rng.choice(BOT_NAMES)


# --------------------------------------------------------------- оценка руки

def estimate_tricks(hand: list[C.Card], trump: int) -> float:
    """Сколько взяток примерно возьмёт рука при таком козыре.

    Козыри взвешиваем по старшинству: туз в руке почти всегда даёт взятку,
    король — если туза нет у соперников, и так далее. Прочие старшие карты
    дают взятку, если их не отобьют козырём.
    """
    if trump == C.NO_TRUMP:
        est = 1.0
        for suit in C.SUIT_ORDER:
            cards = [c for c in hand if c.suit == suit]
            if not cards:
                continue
            top = max(cards, key=lambda c: c.rank)
            if top.rank == 14:
                est += 1.2
            elif top.rank == 13:
                est += 0.7
            elif top.rank == 12:
                est += 0.3
        return est

    est = 0.4
    for card in hand:
        if card.suit != trump:
            continue
        if card.rank == 14:
            est += 1.0
        elif card.rank == 13:
            est += 0.55
        elif card.rank == 12:
            est += 0.35
        else:
            est += 0.3
    for suit in C.SUIT_ORDER:
        if suit == trump:
            continue
        cards = [c for c in hand if c.suit == suit]
        if not cards:
            continue
        top = max(cards, key=lambda c: c.rank)
        if top.rank == 14:
            est += 0.85
        elif top.rank == 13:
            est += 0.4
        elif top.rank == 12:
            est += 0.18
    return est


def _best_trump(hand: list[C.Card]) -> int:
    best_suit, best_est = 0, -1.0
    for suit in C.SUIT_ORDER:
        est = estimate_tricks(hand, suit)
        if est > best_est:
            best_suit, best_est = suit, est
    return best_suit


def _max_tricks_for(hand: list[C.Card], trump: int) -> int:
    est = estimate_tricks(hand, trump)
    n = 0
    for candidate in range(R.MIN_TRICKS, R.MAX_TRICKS + 1):
        if est >= candidate + 0.6:
            n = candidate
    return n


# ------------------------------------------------------------------- решения

def choose_open(game: Game, seat: int, rng: random.Random) -> bool:
    """Открывать ли карты. Бот иногда играет вслепую — это gamble на удвоенную ставку."""
    if not game.can_open_cards(seat):
        return False
    return rng.random() < 0.7


def choose_bid(game: Game, seat: int, rng: random.Random) -> tuple[str, int | None]:
    player = game.players[seat]
    hand = player.hand
    margin = 1.0 + rng.random() * 0.8
    available = game.available_bids()
    if not available:
        return "pass", None

    if game.miser_bid is not None:
        # на столе мизер — перебиваем его заявкой на 9, если рука позволяет
        est = max(estimate_tricks(hand, s) for s in C.SUIT_ORDER)
        if est >= 4.2:
            return "contract", available[0]
        return "pass", None

    if game.blind_bidder is not None and game.current_bid is not None:
        # слепую заявку перебивает только контракт следующего уровня
        est = max(estimate_tricks(hand, s) for s in C.SUIT_ORDER)
        if est >= 4.0 and available:
            return "contract", available[0]
        return "pass", None

    has_winner = any(c.rank >= 13 for c in hand)
    if game.current_bid is None:
        # открываем торг
        if not has_winner:
            if game.can_declare_miser(seat) and rng.random() < 0.6:
                return "miser", None
            return "pass", None
        best = max(C.SUIT_ORDER, key=lambda s: estimate_tricks(hand, s))
        est = estimate_tricks(hand, best)
        if est >= 3.4 + rng.random() * 0.6:
            return "contract", available[0]
        if game.can_declare_miser(seat) and rng.random() < 0.2:
            return "miser", None
        return "pass", None

    # поддерживаем или повышаем контракт
    best_index: int | None = None
    for index in available:
        contract = R.CONTRACTS[index]
        if estimate_tricks(hand, contract.trump) >= contract.tricks + margin:
            best_index = index
    if best_index is None:
        return "pass", None
    return "contract", best_index


def choose_drop(game: Game, seat: int, rng: random.Random) -> list[int]:
    player = game.players[seat]
    trump = game.trump()
    hand = player.hand
    miser = game.round_type == ROUND_MIZER

    def value(card: C.Card) -> tuple:
        is_trump = C.is_trump(card, trump)
        if miser:
            # в мизере держим низкие карты, выкидываем старшие
            return (0 if is_trump else 1, -card.rank)
        # тузы и короли дороги, козыри дороги, мелочь — нет
        return (1 if is_trump else 0, card.rank)

    ordered = sorted(hand, key=value)
    if miser:
        # сбрасываем две самые старшие карты
        return [ordered[0].id, ordered[1].id]

    # иногда сбрасываем не самую слабую, а две слабые из разных мастей
    if len(ordered) >= 4 and rng.random() < 0.25:
        first = ordered[0]
        others = [c for c in ordered[1:] if c.suit != first.suit]
        second = others[0] if others else ordered[1]
        return [first.id, second.id]
    return [ordered[0].id, ordered[1].id]


def choose_whist(game: Game, seat: int, rng: random.Random) -> str:
    player = game.players[seat]
    if game.contract is None:
        return "pass"
    trump = game.contract.trump
    est = estimate_tricks(player.hand, trump)
    half = game.contract.tricks in R.HALF_WHIST_CONTRACTS
    need = R.whist_requirement(game.contract.tricks, half)
    reward = R.whist_reward(game.contract.tricks, half, game.variant)
    if half:
        # полвиста выгоднее, если вист вообще недоступен
        if est >= need - 0.3 and rng.random() < 0.8:
            return "half"
        return "pass"
    if est >= need - 0.2:
        return "vist"
    return "pass"


def choose_catch_mizer(game: Game, seat: int, rng: random.Random) -> bool:
    player = game.players[seat]
    est = max(estimate_tricks(player.hand, s) for s in C.SUIT_ORDER)
    # ловить мизер выгодно, когда рука сильная
    return est >= 4.0 + rng.random() * 0.6


def choose_whist_mode(game: Game, seat: int, rng: random.Random) -> bool:
    """Вистующий выбирает: вслепую (ставки удваиваются) или открыто.

    Открыто — если рука позволяет взять нужное число взяток,
    вслепую — gamble на удвоенную премию.
    """
    player = game.players[seat]
    if game.contract is None:
        return False
    need = R.whist_requirement(game.contract.tricks, game.half_whist)
    est = max(estimate_tricks(player.hand, s) for s in C.SUIT_ORDER)
    if est >= need - 0.2:
        return False
    return rng.random() < 0.5


def _lowest(cards: list[C.Card]) -> C.Card:
    return min(cards, key=lambda c: c.rank)


def _highest(cards: list[C.Card]) -> C.Card:
    return max(cards, key=lambda c: c.rank)


def choose_card(game: Game, seat: int, rng: random.Random) -> int:
    player = game.players[seat]
    legal = game.legal_cards(seat)
    if not legal:
        legal = list(player.hand)
    if not legal:
        raise RuntimeError("у бота нет карт")

    trump = game.trump()
    is_mizer = game.round_type == ROUND_MIZER and seat == game.miser_player
    need_all = game.round_type == ROUND_CONTRACT and game.contract is not None and game.contract.tricks == 10
    wants_tricks = _wants_tricks(game, seat)

    trick_cards = [c for _s, c in game.trick]
    best_in_trick = None
    if trick_cards:
        best_in_trick = C.trick_winner(trick_cards, trump, game.lead_suit)

    if not game.trick:
        # свой ход
        if is_mizer:
            non_trump = [c for c in legal if not C.is_trump(c, trump)]
            pool = non_trump or legal
            return _lowest(pool).id
        if need_all:
            trumps = [c for c in legal if C.is_trump(c, trump)]
            if trumps:
                return _highest(trumps).id
            return _highest(legal).id
        if game.round_type == ROUND_MIZER:
            # соперник в мизере обязан забрать взятку — ведём старшей картой
            by_suit: dict[int, list[C.Card]] = {}
            for card in legal:
                by_suit.setdefault(card.suit, []).append(card)
            suit = max(by_suit, key=lambda s: (len(by_suit[s]), s))
            return _highest(by_suit[suit]).id
        # отыгрываем заведомую взятку
        aces = [c for c in legal if c.rank == 14]
        if aces:
            return _lowest(aces).id
        trumps = [c for c in legal if C.is_trump(c, trump)]
        if len(trumps) >= 3:
            return _lowest(trumps).id
        # иначе ходим из самой длинной масти
        by_suit = {}
        for card in legal:
            by_suit.setdefault(card.suit, []).append(card)
        suit = max(by_suit, key=lambda s: (len(by_suit[s]), s))
        return _lowest(by_suit[suit]).id

    # ответ на взятку
    if is_mizer:
        # мизер: избегаем выигрыша взятки и стараемся не козырить
        if best_in_trick is not None:
            safe = [c for c in legal if not _beats_in_trick(c, best_in_trick, trump, game.lead_suit)]
            if safe:
                return _lowest(safe).id
        non_trump = [c for c in legal if not C.is_trump(c, trump)]
        pool = non_trump or legal
        return _lowest(pool).id

    if need_all:
        if best_in_trick is not None:
            winners = [c for c in legal if _beats_in_trick(c, best_in_trick, trump, game.lead_suit)]
            if winners:
                return _lowest(winners).id
        return _highest(legal).id if trump == C.NO_TRUMP else _lowest(legal).id

    if wants_tricks and best_in_trick is not None:
        winners = [c for c in legal if _beats_in_trick(c, best_in_trick, trump, game.lead_suit)]
        if winners:
            return _lowest(winners).id
        if C.is_trump(best_in_trick, trump):
            return _lowest(legal).id

    # не можем взять взятку — отбрасываем самое бесполезное
    if not wants_tricks:
        # распасы: избегаем взяток, играем минимальной картой своей масти
        if best_in_trick is not None:
            safe = [c for c in legal if not _beats_in_trick(c, best_in_trick, trump, game.lead_suit)]
            if safe:
                return _lowest(safe).id
        return _lowest(legal).id

    # обычный ход: стараемся не отдавать козыри без нужды
    trumps = [c for c in legal if C.is_trump(c, trump)]
    if trumps and len(trumps) > 1 and trump != C.NO_TRUMP:
        non_trump = [c for c in legal if not C.is_trump(c, trump)]
        if non_trump:
            return _lowest(non_trump).id
    return _lowest(legal).id


def _beats_in_trick(candidate: C.Card, best: C.Card, trump: int | None, lead_suit: int | None) -> bool:
    return C.beats(candidate, best, trump, lead_suit)


def _wants_tricks(game: Game, seat: int) -> bool:
    """Хочет ли игрок взять взятку.

    В мизере мизер взяток избегает, а соперники наоборот отбирают их
    (тогда мизер не сможет сыграть). В распасах все избегают взяток.
    """
    if game.round_type == ROUND_MIZER:
        return seat != game.miser_player
    if game.round_type == ROUND_RASPAS:
        return False
    return True
