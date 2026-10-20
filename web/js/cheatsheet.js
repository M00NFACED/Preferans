/* Шпаргалка: сколько взяток набирает комбинация и как поймать мизера.
   Данные — из классических «Правил преферанса» (1971), раздел 5. */
(function (global) {
  "use strict";

  const SMALL = [7, 8, 9, 10];        // «маленькие» карты
  const A = 14, K = 13, Q = 12, J = 11;

  // Комбинации: нужные ранги + сколько маленьких + сколько это взяток
  const COMBOS = [
    { ranks: [A], small: 0, tricks: 1, text: "Туз" },
    { ranks: [A, K], small: 0, tricks: 2, text: "Туз, Король" },
    { ranks: [A, K, Q], small: 0, tricks: 3, text: "Туз, Король, Дама" },
    { ranks: [A, K, Q, J], small: 0, tricks: 4, text: "Туз, Король, Дама, Валет" },
    { ranks: [A, K, Q, J], small: 1, tricks: 5, text: "Туз, Король, Дама, Валет, 1 маленькая" },
    { ranks: [A, K, Q, J], small: 2, tricks: 6, text: "Туз, Король, Дама, Валет, 2 маленьких" },
    { ranks: [A, K, Q, J], small: 3, tricks: 7, text: "Туз, Король, Дама, Валет, 3 маленьких" },
    { ranks: [A, K, Q, J], small: 4, tricks: 8, text: "Туз, Король, Дама, Валет, 4 маленьких" },
    { ranks: [A, K], small: 2, tricks: 3, text: "Туз, Король, 2 маленьких" },
    { ranks: [A, K], small: 3, tricks: 4.5, text: "Туз, Король, 3 маленьких" },
    { ranks: [A, K], small: 4, tricks: 6, text: "Туз, Король, 4 маленьких" },
    { ranks: [A, Q], small: 0, tricks: 1, text: "Туз, Дама" },
    { ranks: [A, Q, J], small: 0, tricks: 1, text: "Туз, Дама, Валет" },
    { ranks: [A, Q, J], small: 1, tricks: 2.5, text: "Туз, Дама, Валет, 1 маленькая" },
    { ranks: [A, Q, J], small: 2, tricks: 3.5, text: "Туз, Дама, Валет, 2 маленьких" },
    { ranks: [A, Q, J], small: 3, tricks: 6.5, text: "Туз, Дама, Валет, 3 маленьких" },
    { ranks: [A, Q, J], small: 4, tricks: 7, text: "Туз, Дама, Валет, 4 маленьких" },
    { ranks: [A, J], small: 0, tricks: 1, text: "Туз, Валет" },
    { ranks: [A, J], small: 1, tricks: 1, text: "Туз, Валет, 1 маленькая" },
    { ranks: [A, J], small: 2, tricks: 2, text: "Туз, Валет, 2 маленьких" },
    { ranks: [A, J], small: 3, tricks: 4.5, text: "Туз, Валет, 3 маленьких" },
    { ranks: [A, J], small: 4, tricks: 5.5, text: "Туз, Валет, 4 маленьких" },
    { ranks: [A], small: 2, tricks: 1, text: "Туз, 2 маленьких" },
    { ranks: [A], small: 3, tricks: 1.5, text: "Туз, 3 маленьких" },
    { ranks: [A], small: 4, tricks: 2.5, text: "Туз, 4 маленьких" },
    { ranks: [K], small: 0, tricks: 0, text: "Король" },
    { ranks: [K, Q], small: 0, tricks: 0.8, text: "Король, Дама (марьяж)", range: [0.7, 1] },
    { ranks: [K, Q, J], small: 0, tricks: 1.7, text: "Король, Дама, Валет (трильяж)", range: [1.5, 2] },
    { ranks: [K, Q, J], small: 1, tricks: 3, text: "Король, Дама, Валет, 1 маленькая" },
    { ranks: [K, Q], small: 2, tricks: 3, text: "Король, Дама, 2 маленьких" },
    { ranks: [K, Q], small: 3, tricks: 4, text: "Король, Дама, 3 маленьких" },
    { ranks: [K, Q], small: 4, tricks: 5, text: "Король, Дама, 4 маленьких" },
    { ranks: [K, Q, J], small: 4, tricks: 6, text: "Король, Дама, Валет, 4 маленьких" },
    { ranks: [K, J], small: 0, tricks: 0, text: "Король, Валет" },
    { ranks: [K, J], small: 1, tricks: 0, text: "Король, Валет, маленькая" },
    { ranks: [K, J], small: 2, tricks: 1.2, text: "Король, Валет, 2 маленьких", range: [0.5, 2] },
    { ranks: [K, J], small: 3, tricks: 2.5, text: "Король, Валет, 3 маленьких" },
    { ranks: [K, J], small: 4, tricks: 4.5, text: "Король, Валет, 4 маленьких" },
    { ranks: [Q, J], small: 0, tricks: 0, text: "Дама, Валет" },
    { ranks: [Q, J], small: 1, tricks: 0.2, text: "Дама, Валет, 1 маленькая", range: [0, 0.3] },
    { ranks: [Q, J], small: 2, tricks: 1, text: "Дама, Валет, 2 маленьких", range: [0.5, 1.5] },
    { ranks: [Q, J], small: 3, tricks: 3, text: "Дама, Валет, 3 маленьких" },
    { ranks: [Q, J], small: 4, tricks: 4.5, text: "Дама, Валет, 4 маленьких" },
    { ranks: [J], small: 2, tricks: 0, text: "Валет, 2 маленьких" },
    { ranks: [J], small: 3, tricks: 0.5, text: "Валет, 3 маленьких", range: [0, 1] },
    { ranks: [J], small: 4, tricks: 1, text: "Валет, 4 маленьких", range: [0, 2] },
    { ranks: [], small: 4, tricks: 1, text: "4 маленьких", range: [0, 2] }
  ];

  // Дыры: каких карт мизеристу не хватает в масти -> вероятность поймать
  const HOLES = [
    { text: "7, 10", p: 0.5, note: "50%" },
    { text: "7, 9", p: 0.05, note: "5% (при ходе мизериста)" },
    { text: "7, Валет", p: 0.8, note: "80%" },
    { text: "7, Дама", p: 0.95, note: "95%" },
    { text: "8", p: 0.05, note: "5% своим ходом, 30% ходом ловящих" },
    { text: "8, 9", p: 0.8, note: "80%" },
    { text: "9", p: 0.15, note: "15% своим ходом, 80–90% чужим" },
    { text: "7, 8 или 9, Дама", p: 0.2, note: "20%" },
    { text: "7, 8 или 9, Король", p: 0.7, note: "70%" },
    { text: "7, 8 или 9, Туз", p: 0.97, note: "почти всегда" },
    { text: "7, 8 или 9, 10 или Валет, Туз", p: 0.1, note: "10%" }
  ];

  const RANK_TEXT = { 7: "7", 8: "8", 9: "9", 10: "10", 11: "В", 12: "Д", 13: "К", 14: "Т" };

  function rankCounts(cards) {
    const counts = {};
    cards.forEach((c) => { counts[c.rank] = (counts[c.rank] || 0) + 1; });
    return counts;
  }

  function smallCount(cards) {
    return cards.filter((c) => SMALL.indexOf(c.rank) >= 0).length;
  }

  /** Какие комбинации из таблицы есть в руке. */
  function matchCombos(cards) {
    const counts = rankCounts(cards);
    const smalls = smallCount(cards);
    const matched = COMBOS.filter((combo) => {
      const need = {};
      combo.ranks.forEach((r) => { need[r] = (need[r] || 0) + 1; });
      for (const rank in need) {
        if ((counts[rank] || 0) < need[rank]) return false;
      }
      return smalls >= combo.small;
    });
    matched.sort((a, b) => b.tricks - a.tricks);
    return matched;
  }

  function ranksOfHole(text) {
    const ranks = [];
    if (text.indexOf("7") >= 0) ranks.push(7);
    if (text.indexOf("8 или 9") >= 0) ranks.push(8, 9);
    else {
      if (text.indexOf("8") >= 0) ranks.push(8);
      if (text.indexOf("9") >= 0) ranks.push(9);
    }
    if (text.indexOf("10") >= 0) ranks.push(10);
    if (text.indexOf("Валет") >= 0) ranks.push(11);
    if (text.indexOf("Дама") >= 0) ranks.push(12);
    if (text.indexOf("Король") >= 0) ranks.push(13);
    if (text.indexOf("Туз") >= 0) ranks.push(14);
    return ranks;
  }

  /**
   * Анализ «дыр» для ловли ми��ера.
   * cards — рука ловящего. Дыра в масти возможна, если ловящий держит
   * все карты паттерна (значит, у мизериста их точно нет).
   */
  function holeAnalysis(cards) {
    const suits = [0, 1, 2, 3];
    const perSuit = suits.map((suit) => {
      const mine = cards.filter((c) => c.suit === suit);
      const found = HOLES.map((h) => {
        const ranks = ranksOfHole(h.text);
        const possible = ranks.length > 0 && ranks.every((r) => mine.some((c) => c.rank === r));
        return { hole: h, possible, ranks };
      }).filter((x) => x.possible);
      found.sort((a, b) => b.hole.p - a.hole.p);
      return { suit, found };
    });
    let best = null;
    perSuit.forEach((entry) => {
      if (entry.found.length && (!best || entry.found[0].hole.p > best.hole.p)) {
        best = { suit: entry.suit, hole: entry.found[0].hole };
      }
    });
    return { perSuit, best };
  }

  global.Cheat = {
    COMBOS, HOLES, RANK_TEXT, SMALL,
    matchCombos, holeAnalysis, rankCounts, smallCount, ranksOfHole
  };
})(window);
