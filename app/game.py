"""Движок партии: торг, прикуп и снос, назначение контракта, вист, взятки, расчёт.

Игра идёт по фазам:

    lobby → auction → drop → declare → whist → playing → round_end → (новый раунд)
                  ↘ (все пасуют) → playing (распасы)

Фаза мизера: auction → drop → catch_mizer → playing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import cards as C
from . import rules as R

PHASE_LOBBY = "lobby"
PHASE_AUCTION = "auction"
PHASE_DROP = "drop"
PHASE_DECLARE = "declare"
PHASE_WHIST = "whist"
PHASE_WHIST_MODE = "whist_mode"   # вистующий выбирает: вслепую или открыто
PHASE_CATCH_MIZER = "catch_mizer"
PHASE_PLAYING = "playing"
PHASE_ROUND_END = "round_end"
PHASE_MATCH_END = "match_end"

ROUND_CONTRACT = "contract"
ROUND_MIZER = "miser"
ROUND_RASPAS = "raspas"

STATUS_WAIT = "wait"
STATUS_PASS = "pass"
STATUS_DECLARER = "declarer"
STATUS_VIST = "vist"
STATUS_MIZER = "mizer"
STATUS_DONE = "done"

HAND_SIZE = 10
TALON_SIZE = 2
TOTAL_TRICKS = 10


class GameError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass
class Player:
    seat: int
    pid: str
    name: str
    is_bot: bool = False
    hand: list[C.Card] = field(default_factory=list)
    tricks: int = 0
    bullet: int = 0
    mountain: int = 0
    vists: int = 0
    status: str = STATUS_WAIT
    bid: int | None = None          # контракт, который игрок назвал на торге
    blind_bid: bool = False         # эта заявка сделана вслепую
    miser_bid: bool = False         # игрок заявил мизер
    passed: bool = False            # игрок уже пасовал в этой раздаче
    order_bribe: int | None = None  # контракт, объявленный после выигрыша торга
    whist_kind: str | None = None   # vist | half | pass
    catch_mizer: bool | None = None
    blind: bool = False            # игрок не видит своих карт
    opened: bool = True            # игрок уже посмотрел свои карты
    folded: bool = False
    trick_taken: list[int] = field(default_factory=list)  # номера взяток, взятых игроком


class Game:
    """Состояние одной партии. Не зависит от транспорта (websocket/http)."""

    def __init__(
        self,
        players: list[Player],
        variant: int = R.VARIANT_SOCHI,
        max_bullet: int = 30,
        seed: int | None = None,
        blind_allowed: bool = False,
    ):
        self.players = players
        self.variant = variant
        self.max_bullet = max_bullet
        self.blind_allowed = blind_allowed
        self.phase = PHASE_LOBBY
        self.round_number = 0
        self.turn: int | None = None
        self.dealer = -1
        self.log: list[str] = []

        self.round_type: str = ""
        self.current_bid: int | None = None
        self.current_bidder: int | None = None
        self.auction_passes = 0
        self.miser_player: int | None = None
        self.miser_bid: int | None = None
        self.miser_blind = False
        self.current_bid_blind = False
        self.blind_bidder: int | None = None   # кто объявил контракт вслепую
        self.blind_declarer = False             # заказчик играет вслепую
        self.blind_whist = False                # вистующий играет вслепую
        self.whist_dark = False
        self.declarer: int | None = None
        self.contract: R.Contract | None = None
        self.without_three = False
        self.whist_player: int | None = None
        self.half_whist = False
        self.talon: list[C.Card] = []
        self.trick: list[tuple[int, C.Card]] = []
        self.lead_suit: int | None = None
        self.leader: int | None = None
        self.tricks_played = 0
        self.rasspas_series = 1
        self.raspas_lead_suits: list[int] = []
        self.last_result: dict | None = None
        self.round_types: list[str] = []
        self.round_history: list[dict] = []
        self.pending = False
        self._rng = random.Random(seed)

    # ---------------------------------------------------------------- служебное

    def _log(self, text: str) -> None:
        self.log.append(text)
        if len(self.log) > 120:
            del self.log[:-120]

    def player(self, seat: int) -> Player:
        return self.players[seat]

    def next_seat(self, seat: int) -> int:
        return (seat + 1) % len(self.players)

    def opponents_of(self, seat: int) -> list[int]:
        return [s for s in range(len(self.players)) if s != seat]

    def open_hands(self) -> bool:
        """В мизере карты соперников открыты — так в оригинальной игре."""
        return self.round_type == ROUND_MIZER

    # ------------------------------------------------------------------ раздача

    def start_round(self) -> None:
        self.round_number += 1
        self.dealer = (self.dealer + 1) % len(self.players)
        for p in self.players:
            p.hand = []
            p.tricks = 0
            p.bid = None
            p.blind_bid = False
            p.miser_bid = False
            p.passed = False
            p.blind = False
            p.opened = not self.blind_allowed   # в слепой игре карты раздаются закрытыми
            p.order_bribe = None
            p.whist_kind = None
            p.catch_mizer = None
            p.folded = False
            p.status = STATUS_WAIT
            p.trick_taken = []

        deck = C.shuffled_deck(self._rng)
        self.talon = []
        for i, card in enumerate(deck):
            if i < HAND_SIZE * len(self.players):
                self.players[i % len(self.players)].hand.append(card)
            else:
                self.talon.append(card)
        for p in self.players:
            p.hand = C.sort_hand(p.hand)

        self.current_bid = None
        self.current_bidder = None
        self.current_bid_blind = False
        self.auction_passes = 0
        self.miser_player = None
        self.miser_bid = None
        self.miser_blind = False
        self.blind_bidder = None
        self.blind_declarer = False
        self.blind_whist = False
        self.whist_dark = False
        self.declarer = None
        self.contract = None
        self.without_three = False
        self.whist_player = None
        self.half_whist = False
        self.trick = []
        self.lead_suit = None
        self.leader = None
        self.tricks_played = 0
        self.raspas_lead_suits = []
        self.last_result = None
        self.pending = False

        self.phase = PHASE_AUCTION
        self.turn = self.dealer
        self._log(f"Раунд {self.round_number}. Торг начал(а) {self.players[self.dealer].name}.")

    # -------------------------------------------------------------------- торг

    def available_bids(self) -> list[int]:
        """Контракты, которые можно назвать прямо сейчас (строго выше текущего)."""
        if self.miser_bid is not None:
            # мизер перебивается только заявкой на 9 (и выше)
            return [i for i in range(R.CONTRACT_COUNT) if R.CONTRACTS[i].tricks >= 9]
        if self.current_bid_blind and self.current_bid is not None:
            # слепую заявку можно перебить только контрактом следующего уровня
            level = R.CONTRACTS[self.current_bid].tricks + 1
            return [i for i in range(R.CONTRACT_COUNT) if R.CONTRACTS[i].tricks == level]
        if self.current_bid is None:
            return list(range(R.CONTRACT_COUNT))
        return [i for i in range(self.current_bid + 1, R.CONTRACT_COUNT)]

    def can_bid_blind(self, seat: int) -> bool:
        """Доступна ли слепая заявка этому игроку (он ещё не открывал карты)."""
        if not self.blind_allowed:
            return False
        if self.phase != PHASE_AUCTION or self.turn != seat:
            return False
        if self.current_bid_blind and self.current_bid is not None:
            return False
        player = self.players[seat]
        if player.bid is not None or player.passed or player.opened:
            return False
        return True

    def can_open_cards(self, seat: int) -> bool:
        """Может ли игрок открыть свои карты прямо сейчас."""
        if not self.blind_allowed:
            return False
        if self.phase != PHASE_AUCTION or self.turn != seat:
            return False
        player = self.players[seat]
        if player.opened or player.passed:
            return False
        return True

    def open_cards(self, seat: int) -> None:
        """Игрок открывает свою руку и дальше торгует уже видя карты."""
        if not self.can_open_cards(seat):
            raise GameError("bad_phase", "Сейчас нельзя открыть карты.")
        player = self.players[seat]
        player.opened = True
        player.blind = False
        self._log(f"{player.name} открыл карты.")
        # ход остаётся за ним: дальше он заявляет контракт как обычно

    def can_declare_miser(self, seat: int) -> bool:
        """Мизер — только первая заявка игрока в этой раздаче (и не после паса)."""
        if self.phase != PHASE_AUCTION or self.turn != seat:
            return False
        if self.miser_bid is not None:
            return False
        player = self.players[seat]
        if player.bid is not None or player.passed:
            return False
        current_tricks = R.CONTRACTS[self.current_bid].tricks if self.current_bid is not None else R.MIN_TRICKS
        return current_tricks <= 8
    def bid(self, seat: int, kind: str, contract_index: int | None = None, blind: bool = False) -> None:
        if self.phase != PHASE_AUCTION:
            raise GameError("not_auction", "Сейчас не идёт торг.")
        if self.turn != seat:
            raise GameError("not_your_turn", "Не ваш ход.")

        player = self.players[seat]
        if not player.opened:
            # карты закрыты — заявка автоматически считается слепой
            blind = True
        if kind == "pass":
            if player.miser_bid:
                raise GameError("bad_bid", "От мизера, который ты выиграл, нельзя отказаться.")
            player.status = STATUS_PASS
            player.passed = True
            player.bid = None
            player.blind_bid = False
            self.auction_passes += 1
            self._log(f"{player.name}: пас.")
            self._recompute_bid()
            self._after_auction_step()
            return

        if kind == "miser":
            if not self.can_declare_miser(seat):
                raise GameError("bad_miser", "Мизер сейчас объявить нельзя.")
            if not player.opened:
                blind = True
            self.miser_bid = seat
            self.miser_player = seat
            self.miser_blind = blind
            player.miser_bid = True
            player.status = STATUS_MIZER
            self.round_type = ROUND_MIZER
            tail = " ВСЛЕПУЮ" if blind else ""
            self._log(f"{player.name}: МИЗЕР{tail}! (её можно перебить заявкой на 9)")
            self.turn = self._next_active(seat)
            return

        if kind != "contract" or contract_index is None:
            raise GameError("bad_bid", "Некорректная заявка.")
        if contract_index not in self.available_bids():
            raise GameError("bad_bid", "Заявка должна быть выше предыдущей.")
        if blind and not self.can_bid_blind(seat) and not player.opened:
            raise GameError("bad_bid", "Слепая заявка сейчас недоступна.")

        if self.miser_bid is not None:
            beaten = self.miser_bid
            self._log(f"Мизер перебит заявкой {R.contract_name(contract_index)}.")
            self.miser_bid = None
            self.miser_player = None
            self.miser_blind = False
            self.round_type = ""
            self.players[beaten].miser_bid = False
            self.players[beaten].status = STATUS_WAIT

        player.bid = contract_index
        player.blind_bid = blind
        player.status = STATUS_WAIT
        self.current_bid = contract_index
        self.current_bidder = seat
        self.current_bid_blind = blind
        self.auction_passes = 0
        if blind:
            self._log(f"{player.name}: {R.contract_name(contract_index)} ВСЛЕПУЮ!")
        else:
            self._log(f"{player.name}: {R.contract_name(contract_index)}.")
        self.turn = self._next_active(seat)

    def _recompute_bid(self) -> None:
        """Пересчитывает текущую (самую старшую) заявку среди участников торговли."""
        best_seat = None
        best_bid = None
        for seat, player in enumerate(self.players):
            if player.passed or player.bid is None:
                continue
            if best_bid is None or player.bid > best_bid:
                best_bid = player.bid
                best_seat = seat
        if best_seat is None:
            self.current_bid = None
            self.current_bidder = None
            self.current_bid_blind = False
        else:
            self.current_bid = best_bid
            self.current_bidder = best_seat
            self.current_bid_blind = self.players[best_seat].blind_bid

    def _after_auction_step(self) -> None:
        # торг заканчивается, когда в игре остался один участник
        active = [s for s in range(len(self.players)) if not self.players[s].passed]
        if len(active) <= 1:
            winner = active[0] if active else None
            has_bid = winner is not None and (
                self.players[winner].bid is not None
                or self.players[winner].miser_bid
            )
            if has_bid:
                self._finish_auction(winner)
            else:
                self._start_raspas()
            return
        self.turn = self._next_active(self.turn)

    def _next_active(self, seat: int) -> int:
        """Следующий игрок, который ещё не спасул (пас = выбывание)."""
        count = len(self.players)
        for offset in range(1, count + 1):
            candidate = (seat + offset) % count
            if not self.players[candidate].passed:
                return candidate
        return seat

    def _finish_auction(self, winner: int) -> None:
        self.declarer = winner
        player = self.players[winner]
        if player.miser_bid:
            self.round_type = ROUND_MIZER
            player.status = STATUS_MIZER
            if self.miser_blind:
                self.blind_declarer = True
                player.blind = True
                self._log(f"{player.name} играет МИЗЕР ВСЛЕПУЮ (ставки удваиваются).")
        else:
            self.round_type = ROUND_CONTRACT
            player.status = STATUS_DECLARER
            if self.current_bid_blind:
                self.blind_declarer = True
                player.blind = True
                self._log(f"{player.name} играет ВСЛЕПУЮ (ставки удваиваются).")
        # после торга карты открываются всем, кроме слепого заказчика
        for other in self.players:
            if not other.blind:
                other.opened = True
        self._log(f"Контракт заказывает {player.name}.")
        self._declarer_takes_talon()

    def _declarer_takes_talon(self) -> None:
        """Заказчик определился: прикуп раскрывают для всех, но в руку он попадёт
        только после сноса двух карт."""
        assert self.declarer is not None
        declarer = self.players[self.declarer]
        self.phase = PHASE_DROP
        self.turn = self.declarer
        self._log(f"{declarer.name} сбрасывает две карты, потом берёт прикуп.")

    def _start_raspas(self) -> None:
        self.round_type = ROUND_RASPAS
        self.phase = PHASE_PLAYING
        self.leader = self.dealer
        self.turn = self.dealer
        self.lead_suit = None
        self.raspas_lead_suits = [c.suit for c in self.talon]
        for player in self.players:
            player.opened = True
            player.blind = False
        self._log("Все спасуют — играются распасы.")

    # --------------------------------------------------------------------- снос

    def drop(self, seat: int, card_ids: list[int]) -> None:
        if self.phase != PHASE_DROP or self.turn != seat:
            raise GameError("bad_phase", "Сейчас нельзя сбрасывать карты.")
        ids = list(card_ids)
        if len(ids) != 2 or len(set(ids)) != 2:
            raise GameError(
                "bad_drop",
                f"Нужно сбросить ровно две карты (получено {ids}, "
                f"на руках {len(self.players[seat].hand)}).",
            )
        hand = self.players[seat].hand
        chosen = []
        for cid in ids:
            found = next((c for c in hand if c.id == cid), None)
            if found is None:
                raise GameError("bad_drop", "Такой карты нет на руках.")
            chosen.append(found)
        for card in chosen:
            hand.remove(card)
        # только теперь прикуп уходит заказчику в руку
        declarer = self.players[seat]
        if self.talon:
            declarer.hand = C.sort_hand(declarer.hand + self.talon)
            self._log(f"{declarer.name} берёт прикуп: "
                      + ", ".join(f"{C.SUIT_SYMBOL[c.suit]}{c.label}" for c in self.talon))
        self.talon = []
        declarer.hand = C.sort_hand(declarer.hand)
        self._log(f"{declarer.name} сбросил две карты.")

        if self.round_type == ROUND_MIZER:
            self.phase = PHASE_CATCH_MIZER
            self.turn = self.next_seat(self.declarer)
        else:
            self.phase = PHASE_DECLARE
            self.turn = self.declarer

    # ------------------------------------------------------------- контракт/вист

    def declare(self, seat: int, contract_index: int, without_three: bool = False) -> None:
        if self.phase != PHASE_DECLARE or self.turn != seat:
            raise GameError("bad_phase", "Сейчас нельзя назначить контракт.")
        if not 0 <= contract_index < R.CONTRACT_COUNT:
            raise GameError("bad_contract", "Неизвестный контракт.")
        player = self.players[seat]
        if player.bid is not None and contract_index < player.bid:
            raise GameError("bad_contract", "Контракт не может быть ниже вашей заявки.")
        self.contract = R.contract(contract_index)
        self.without_three = without_three
        player.order_bribe = contract_index
        player.status = STATUS_DECLARER
        self._log(f"Контракт: {self.contract.name}." + (" (без 3 взяток)." if without_three else ""))

        self.phase = PHASE_WHIST
        self.turn = self.next_seat(seat)

    def whist_players(self) -> list[int]:
        """Соперники контрактующего по порядку хода, начиная со следующего за ним."""
        if self.declarer is None:
            return []
        order = []
        seat = self.next_seat(self.declarer)
        for _ in range(len(self.players) - 1):
            order.append(seat)
            seat = self.next_seat(seat)
        return order

    def can_whist(self, seat: int, kind: str) -> tuple[bool, str]:
        if self.phase != PHASE_WHIST or self.turn != seat:
            return False, "Не ваш ход."
        if kind == "half":
            if self.contract is None or self.contract.tricks not in R.HALF_WHIST_CONTRACTS:
                return False, "Полвиста доступен только для контрактов 6 и 7."
            if self.players[seat].whist_kind is not None:
                return False, "Вы уже ответили."
        return True, ""

    def whist(self, seat: int, kind: str) -> None:
        ok, why = self.can_whist(seat, kind)
        if not ok:
            raise GameError("bad_whist", why)
        player = self.players[seat]
        player.whist_kind = kind
        player.status = STATUS_VIST if kind in ("vist", "half") else STATUS_PASS
        if kind in ("vist", "half"):
            self.whist_player = seat
            self.half_whist = kind == "half"
            self._log(f"{player.name}: {'полвиста' if kind == 'half' else 'вист'}.")
        else:
            self._log(f"{player.name}: пас на вист.")

        if all(self.players[s].whist_kind is not None for s in self.whist_players()):
            # если вистующий только один — он выбирает: вслепую или открыто
            takers = [s for s in self.whist_players() if self.players[s].whist_kind in ("vist", "half")]
            if self.blind_allowed and len(takers) == 1:
                self.phase = PHASE_WHIST_MODE
                self.turn = takers[0]
                return
            self._start_playing()
        else:
            self.turn = self.next_seat(seat)

    def whist_mode(self, seat: int, dark: bool) -> None:
        """Вистующий выбирает, играть ли вслепую."""
        if self.phase != PHASE_WHIST_MODE or self.turn != seat:
            raise GameError("bad_phase", "Сейчас нельзя выбирать режим виста.")
        self.whist_dark = dark
        self.blind_whist = dark
        if dark:
            self.players[seat].blind = True
            self._log(f"{self.players[seat].name} вистует ВСЛЕПУЮ (ставки удваиваются).")
        else:
            self._log(f"{self.players[seat].name} вистует открыто.")
        self._start_playing()

    def catch_mizer(self, seat: int, accept: bool) -> None:
        if self.phase != PHASE_CATCH_MIZER or self.turn != seat:
            raise GameError("bad_phase", "Не ваш ход.")
        player = self.players[seat]
        player.catch_mizer = accept
        self._log(f"{player.name} {'ловит мизер' if accept else 'не ловит мизер'}.")
        if all(self.players[s].catch_mizer is not None for s in self.opponents_of(self.miser_player or 0)):
            self._start_playing()
        else:
            self.turn = self.next_seat(seat)

    def _start_playing(self) -> None:
        self.phase = PHASE_PLAYING
        self.leader = self.dealer if self.round_type == ROUND_RASPAS else self.declarer
        self.turn = self.leader
        self.lead_suit = None
        self.trick = []
        self.tricks_played = 0
        self._log("Игра началась.")

    # ------------------------------------------------------------------ взятки

    def required_lead_suit(self, seat: int) -> int | None:
        """В распасах первые две взятки ходятся по масти прикупа."""
        if self.round_type != ROUND_RASPAS or self.tricks_played >= len(self.raspas_lead_suits):
            return None
        suit = self.raspas_lead_suits[self.tricks_played]
        if any(c.suit == suit for c in self.players[seat].hand):
            return suit
        return None

    def legal_cards(self, seat: int) -> list[C.Card]:
        hand = self.players[seat].hand
        if not self.trick:
            required = self.required_lead_suit(seat)
            if required is not None:
                same = [c for c in hand if c.suit == required]
                if same:
                    return same
            return list(hand)
        return C.legal_cards(hand, self.trump(), self.lead_suit)

    def trump(self) -> int | None:
        if self.round_type == ROUND_MIZER:
            return None
        if self.round_type == ROUND_RASPAS:
            return C.NO_TRUMP
        if self.contract is None:
            return None
        return self.contract.trump

    def play(self, seat: int, card_id: int) -> None:
        if self.phase != PHASE_PLAYING:
            raise GameError("bad_phase", "Сейчас нельзя ходить.")
        if self.pending:
            raise GameError("trick_pending", "Взятка ещё разыгрывается — подождите.")
        if self.turn != seat:
            raise GameError("not_your_turn", "Не ваш ход.")
        player = self.players[seat]
        card = next((c for c in player.hand if c.id == card_id), None)
        if card is None:
            raise GameError("no_card", "Такой карты нет на руках.")
        allowed = {c.id for c in self.legal_cards(seat)}
        if card.id not in allowed:
            raise GameError("illegal_card", "Так ходить нельзя.")

        player.hand.remove(card)
        if not self.trick:
            required = self.required_lead_suit(seat)
            self.lead_suit = required if required is not None else card.suit
        self.trick.append((seat, card))
        self._log(f"{player.name}: {C.SUIT_SYMBOL[card.suit]}{card.label}")

        if len(self.trick) < len(self.players):
            self.turn = self.next_seat(seat)
            return
        # Взятка собрана: даём игрокам её увидеть, розыгрыш — позже (см. resolve_pending).
        self.pending = True

    def resolve_pending(self) -> None:
        """Разыгрывает собранную взятку (вызывается, когда все её увидели)."""
        if not self.pending:
            return
        self.pending = False
        self._resolve_trick()

    def _resolve_trick(self) -> None:
        cards = [c for _s, c in self.trick]
        winner_card = C.trick_winner(cards, self.trump(), self.lead_suit)
        winner_seat = next(s for s, c in self.trick if c.id == winner_card.id)
        self.players[winner_seat].tricks += 1
        self.players[winner_seat].trick_taken.append(self.tricks_played)
        self.leader = winner_seat
        self.turn = winner_seat
        self.trick = []
        self.lead_suit = None
        self.tricks_played += 1
        if self.tricks_played >= TOTAL_TRICKS:
            self.settle_round()
        else:
            self._log(f"Взятку взял {self.players[winner_seat].name}.")

    # ------------------------------------------------------------------ расчёт

    def _write_own_bullet(self, seat: int, points: int) -> int:
        """Пишет очки в свою пулю, возвращает количество не влезших очков."""
        player = self.players[seat]
        room = max(0, self.max_bullet - player.bullet)
        fit = min(points, room)
        player.bullet += fit
        player.vists += fit * R.VIST_PER_BULLET
        return points - fit

    def _write_others_bullet(self, seats: list[int], points: int) -> None:
        """Раскидывает очки по чужим пулям: по 10 вистов за каждое очко.

        За один раунд в пули соперников пишется не больше длины пули —
        иначе одна катастрофическая ошибка обнуляет весь матч.
        """
        points = min(points, self.max_bullet)
        for seat, share in zip(seats, R.split_points(points, len(seats))):
            if share <= 0:
                continue
            self.players[seat].bullet += share
            self.players[seat].vists += share * R.VIST_PER_BULLET

    def _mountain_to_points(self, mountain: int) -> int:
        """Очко горы превращается в очки в чужих пулях (7 вистов за очко горы)."""
        return (mountain * R.MOUNTAIN_TO_BULLET_NUM) // R.MOUNTAIN_TO_BULLET_DEN

    def settle_round(self) -> None:
        result = {"round": self.round_number, "type": self.round_type, "lines": []}
        self.round_types.append(self.round_type)
        if self.round_type == ROUND_CONTRACT:
            self._settle_contract(result)
        elif self.round_type == ROUND_MIZER:
            self._settle_mizer(result)
        else:
            self._settle_raspas(result)

        for p in self.players:
            p.status = STATUS_DONE
        self.phase = PHASE_ROUND_END
        self.turn = None
        self.last_result = result
        self.round_history.append(
            {
                "round": self.round_number,
                "type": self.round_type,
                "contract": result.get("contract"),
                "made": result.get("made"),
                "tricks": [p.tricks for p in self.players],
                "declarer": self.declarer,
            }
        )
        if self.match_over():
            self.phase = PHASE_MATCH_END
        self._log("Раунд завершён.")

    def _settle_contract(self, result: dict) -> None:
        assert self.contract is not None and self.declarer is not None
        d = self.declarer
        declarer = self.players[d]
        others = self.opponents_of(d)
        n = self.contract.tricks
        blind = self.blind_declarer
        mult = 2 if blind else 1
        base = R.bullet_premium(n) * mult
        made = declarer.tricks >= n
        result["contract"] = self.contract.name + (" (вслепую)" if blind else "")
        result["made"] = made
        result["tricks_taken"] = declarer.tricks

        if made:
            overflow = self._write_own_bullet(d, base)
            if overflow > 0:
                self._write_others_bullet(others, overflow)
            result["lines"].append(
                f"Контракт {self.contract.name} сыгран ({declarer.tricks} взяток): "
                f"{base - overflow} в пулю, {(base - overflow) * R.VIST_PER_BULLET} вистов."
            )
            if self.contract.tricks == 7:
                self.rasspas_series = 1
        else:
            deficit = n - declarer.tricks
            mountain = deficit * R.mountain_per_trick(n, self.variant) * mult
            declarer.mountain += mountain
            points = self._mountain_to_points(mountain)
            self._write_others_bullet(others, points)
            result["lines"].append(
                f"Контракт {self.contract.name} не сыгран ({declarer.tricks} из {n}): "
                f"{mountain} в гору, {points} в пули соперникам."
            )

        if self.whist_player is not None:
            w = self.players[self.whist_player]
            need = R.whist_requirement(n, self.half_whist)
            wmult = 2 if self.blind_whist else 1
            if w.tricks >= need:
                reward = R.whist_reward(n, self.half_whist, self.variant) * wmult
                w.vists += reward
                declarer.vists -= reward
                result["lines"].append(f"{w.name} взял вист: {reward} вистов.")
            else:
                missing = need - w.tricks
                mountain = missing * R.mountain_per_trick(n, self.variant) * wmult
                w.mountain += mountain
                points = self._mountain_to_points(mountain)
                self._write_own_bullet(d, points)
                result["lines"].append(
                    f"{w.name} не добрал вист ({w.tricks} из {need}): {mountain} в гору."
                )

        if self.without_three:
            if declarer.tricks <= 2:
                overflow = self._write_own_bullet(d, R.WITHOUT_THREE_BULLET)
                result["lines"].append("«Без 3 взяток» выполнено: +2 в пулю.")
            else:
                mountain = R.WITHOUT_THREE_BULLET * R.mountain_per_trick(n, self.variant)
                declarer.mountain += mountain
                points = self._mountain_to_points(mountain)
                self._write_others_bullet(others, points)
                result["lines"].append("«Без 3 взяток» не выполнено.")

    def _settle_mizer(self, result: dict) -> None:
        assert self.miser_player is not None
        m = self.miser_player
        miser = self.players[m]
        others = self.opponents_of(m)
        catchers = [s for s in others if self.players[s].catch_mizer]
        result["contract"] = "Мизер"
        if miser.tricks == 0:
            overflow = self._write_own_bullet(m, R.MIZER_BULLET)
            for s in catchers:
                self.players[s].vists -= R.CATCH_MIZER_BONUS
                miser.vists += R.CATCH_MIZER_BONUS
            result["lines"].append(
                f"Мизер сыгран: {R.MIZER_BULLET - overflow} в пулю, "
                f"{(R.MIZER_BULLET - overflow) * R.VIST_PER_BULLET} вистов."
            )
            self.rasspas_series = 1
        else:
            mountain = miser.tricks * R.MIZER_MOUNTAIN_PER_TRICK * self.variant
            miser.mountain += mountain
            points = self._mountain_to_points(mountain)
            self._write_others_bullet(others, points)
            for s in catchers:
                self.players[s].vists += R.CATCH_MIZER_BONUS
                miser.vists -= R.CATCH_MIZER_BONUS
            result["lines"].append(
                f"Мизер не сыгран ({miser.tricks} взяток): {mountain} в гору."
            )
        result["made"] = miser.tricks == 0

    def _settle_raspas(self, result: dict) -> None:
        cost = self.rasspas_series
        result["contract"] = "Распасы"
        result["made"] = None
        for seat, player in enumerate(self.players):
            if player.tricks > 0:
                mountain = player.tricks * cost
                player.mountain += mountain
                self._write_others_bullet(self.opponents_of(seat), mountain)
                result["lines"].append(
                    f"{player.name}: {player.tricks} взяток — {mountain} в гору."
                )
            else:
                overflow = self._write_own_bullet(seat, cost)
                result["lines"].append(f"{player.name}: ни одной взятки — {cost} в пулю.")
        self.rasspas_series = min(3, self.rasspas_series + 1)

    def match_over(self) -> bool:
        if self.variant == R.VARIANT_LENINGRAD:
            total = sum(p.bullet for p in self.players)
            return total >= self.max_bullet * len(self.players)
        return all(p.bullet >= self.max_bullet for p in self.players)

    # -------------------------------------------------------------------- вид

    def view(self, seat: int | None) -> dict:
        players = []
        for p in self.players:
            players.append(
                {
                    "seat": p.seat,
                    "name": p.name,
                    "is_bot": p.is_bot,
                    "connected": getattr(p, "connected", True),
                    "hand_count": len(p.hand),
                    "tricks": p.tricks,
                    "bullet": p.bullet,
                    "mountain": p.mountain,
                    "vists": p.vists,
                    "status": p.status,
                    "bid": p.bid,
                    "bid_name": R.contract_name(p.bid) if p.bid is not None else None,
                    "miser_bid": p.miser_bid,
                    "passed": p.passed,
                    "opened": p.opened,
                    "order_bribe": p.order_bribe,
                    "whist_kind": p.whist_kind,
                    "catch_mizer": p.catch_mizer,
                    "folded": p.folded,
                }
            )

        view = {
            "phase": self.phase,
            "round": self.round_number,
            "round_type": self.round_type,
            "turn": self.turn,
            "dealer": self.dealer,
            "leader": self.leader,
            "variant": self.variant,
            "variant_name": R.VARIANT_NAMES[self.variant],
            "max_bullet": self.max_bullet,
            "rasspas_series": self.rasspas_series,
            "players": players,
            "contract": self.contract.to_dict() if self.contract else None,
            "without_three": self.without_three,
            "declarer": self.declarer,
            "miser_player": self.miser_player,
            "blind_declarer": self.blind_declarer,
            "blind_whist": self.blind_whist,
            "blind_bidder": self.blind_bidder,
            "current_bid_blind": self.current_bid_blind,
            "whist_player": self.whist_player,
            "half_whist": self.half_whist,
            "blind_allowed": self.blind_allowed,
            "current_bid": self.current_bid,
            "current_bid_name": R.contract_name(self.current_bid) if self.current_bid is not None else None,
            "current_bidder": self.current_bidder,
            "auction_passes": self.auction_passes,
            # прикуп раскрывают только на этапе сноса — и сразу после этого он уходит в руку
            "talon": [c.to_dict() for c in self.talon] if self.phase == PHASE_DROP else [],
            "trick": [{"seat": s, "card": c.to_dict()} for s, c in self.trick],
            "pending": self.pending,
            "lead_suit": self.lead_suit,
            "trump": self.trump(),
            "open_hands": self.open_hands(),
            "last_result": self.last_result,
            "log": self.log[-40:],
        }

        if seat is not None:
            player = self.players[seat]
            view["you"] = seat
            view["blind"] = player.blind
            view["opened"] = player.opened
            if player.blind or not player.opened:
                # карты не открыты — показываем только рубашки
                view["hand"] = [{"id": c.id, "blind": True} for c in player.hand]
            else:
                view["hand"] = [c.to_dict() for c in player.hand]
            view["legal"] = [c.id for c in self.legal_cards(seat)]
            view["available_bids"] = self.available_bids()
            view["can_miser"] = self.can_declare_miser(seat)
            view["can_bid_blind"] = self.can_bid_blind(seat)
            view["can_open"] = self.can_open_cards(seat)
            view["can_declare"] = self.phase == PHASE_DECLARE and self.turn == seat
            view["can_drop"] = self.phase == PHASE_DROP and self.turn == seat
            view["can_whist"] = self.phase == PHASE_WHIST and self.turn == seat
            view["can_whist_mode"] = self.phase == PHASE_WHIST_MODE and self.turn == seat
            view["can_catch_mizer"] = self.phase == PHASE_CATCH_MIZER and self.turn == seat
            view["can_play"] = self.phase == PHASE_PLAYING and self.turn == seat
            view["whist_options"] = self._whist_options(seat)
            if self.open_hands():
                view["open_hands_data"] = {
                    str(p.seat): [c.to_dict() for c in p.hand] for p in self.players if p.seat != seat
                }
        return view

    def _whist_options(self, seat: int) -> list[str]:
        if self.phase != PHASE_WHIST or self.turn != seat:
            return []
        options = ["pass", "vist"]
        if self.contract is not None and self.contract.tricks in R.HALF_WHIST_CONTRACTS:
            options.append("half")
        return options


MIN_DEFAULT = 6
