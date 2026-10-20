"""Колода, масти, старшинство карт и правило определения победителя взятки.

Колода 32 карты: 7-8-9-10-В-Д-К-Т в четырёх мастях (как в игре «Пуля»).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

SPADES = 0
CLUBS = 1
DIAMONDS = 2
HEARTS = 3
NO_TRUMP = 4

SUIT_ORDER = (SPADES, CLUBS, DIAMONDS, HEARTS)
ALL_SUITS = (SPADES, CLUBS, DIAMONDS, HEARTS, NO_TRUMP)

SUIT_FULL = {
    SPADES: "Пики",
    CLUBS: "Трефы",
    DIAMONDS: "Бубны",
    HEARTS: "Червы",
    NO_TRUMP: "Без козыря",
}

SUIT_SHORT = {
    SPADES: "Пик",
    CLUBS: "Треф",
    DIAMONDS: "Бубн",
    HEARTS: "Черв",
    NO_TRUMP: "б/к",
}

SUIT_SYMBOL = {
    SPADES: "♠",
    CLUBS: "♣",
    DIAMONDS: "♦",
    HEARTS: "♥",
    NO_TRUMP: "—",
}

SUIT_ICON = {
    SPADES: "♠",
    CLUBS: "♣",
    DIAMONDS: "♦",
    HEARTS: "♥",
}

RANKS = (7, 8, 9, 10, 11, 12, 13, 14)
RANK_LABEL = {7: "7", 8: "8", 9: "9", 10: "10", 11: "В", 12: "Д", 13: "К", 14: "Т"}


@dataclass(frozen=True)
class Card:
    """Карта. id — индекс в колоде (0..31), стабилен в пределах раздачи."""

    id: int
    suit: int
    rank: int

    @property
    def label(self) -> str:
        return RANK_LABEL[self.rank]

    def to_dict(self) -> dict:
        return {"id": self.id, "suit": self.suit, "rank": self.rank}

    @staticmethod
    def from_dict(data: dict) -> "Card":
        return Card(id=int(data["id"]), suit=int(data["suit"]), rank=int(data["rank"]))


def build_deck() -> list[Card]:
    """Новая колода из 32 карт в фиксированном порядке."""
    cards: list[Card] = []
    cid = 0
    for suit in SUIT_ORDER:
        for rank in RANKS:
            cards.append(Card(id=cid, suit=suit, rank=rank))
            cid += 1
    return cards


def shuffled_deck(rng: random.Random | None = None) -> list[Card]:
    deck = build_deck()
    (rng or random).shuffle(deck)
    return deck


def sort_hand(cards: list[Card]) -> list[Card]:
    """Руки сортируются по масти (♠♣♦♥) и внутри — по убыванию старшинства."""
    return sorted(cards, key=lambda c: (SUIT_ORDER.index(c.suit) if c.suit in SUIT_ORDER else 9, -c.rank))


def is_trump(card: Card, trump: int | None) -> bool:
    return trump is not None and trump != NO_TRUMP and card.suit == trump


def beats(candidate: Card, current: Card, trump: int | None, lead_suit: int | None) -> bool:
    """Бьёт ли candidate текущую карту в взятке."""
    c_trump = is_trump(candidate, trump)
    b_trump = is_trump(current, trump)
    if c_trump != b_trump:
        return c_trump
    if c_trump:
        return candidate.rank > current.rank
    lead = lead_suit if lead_suit is not None else current.suit
    if candidate.suit == lead and current.suit != lead:
        return True
    if current.suit == lead and candidate.suit != lead:
        return False
    if candidate.suit == current.suit:
        return candidate.rank > current.rank
    return False


def trick_winner(cards: list[Card], trump: int | None, lead_suit: int | None) -> Card:
    best = cards[0]
    for card in cards[1:]:
        if beats(card, best, trump, lead_suit):
            best = card
    return best


def legal_cards(hand: list[Card], trump: int | None, lead_suit: int | None) -> list[Card]:
    """Какие карты можно сыграть в ответ на lead_suit (None — ход самому)."""
    if lead_suit is None:
        return list(hand)
    same = [c for c in hand if c.suit == lead_suit]
    if same:
        return same
    trumps = [c for c in hand if is_trump(c, trump)]
    if trumps:
        return trumps
    return list(hand)
