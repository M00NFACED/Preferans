/* Карты: SVG-фигуры мастей, раскладка пипсов, фигурные карты, рубашка. */
(function (global) {
  "use strict";

  // 0 пики, 1 трефы, 2 бубны, 3 черви
  const SUIT_PATHS = {
    0: '<path d="M12 2C12 2 3.5 8.4 3.5 13.9c0 2.8 2.2 4.9 5 4.9 1.3 0 2.5-.5 3.5-1.4-.5 2.6-2 4.4-4 5.2h12c-2-.8-3.5-2.6-4-5.2 1 .9 2.2 1.4 3.5 1.4 2.8 0 5-2.1 5-4.9C20.5 8.4 12 2 12 2z"/>',
    1: '<g><circle cx="12" cy="6.6" r="4.1"/><circle cx="6.9" cy="12.8" r="4.1"/>' +
       '<circle cx="17.1" cy="12.8" r="4.1"/>' +
       '<path d="M12 14.2c2.6 2.7 4 4.7 4 6.2 0 1.4-1 2.4-2.2 2.4-.8 0-1.5-.4-1.8-1-.3.6-1 1-1.8 1-1.2 0-2.2-1-2.2-2.4 0-1.5 1.4-3.5 4-6.2z"/></g>',
    2: '<path d="M12 1.6c.3 0 .6.15.8.4l9.2 9.2c.5.5.5 1.3 0 1.8l-9.2 9.2c-.5.5-1.3.5-1.8 0L1.8 13c-.5-.5-.5-1.3 0-1.8l9.2-9.2c.2-.25.5-.4.8-.4z"/>',
    3: '<path d="M12 21.6C6.4 16.9 2 13.1 2 8.6 2 5.4 4.5 3 7.6 3c1.8 0 3.4.9 4.4 2.3C13 3.9 14.6 3 16.4 3 19.5 3 22 5.4 22 8.6c0 4.5-4.4 8.3-10 13z"/>'
  };

  // раскладка пипсов для 7-10 (в долях от ширины/высоты лицевой части)
  // колонки отодвинуты от углов, чтобы пипсы не наезжали на индекс
  const PIP_LAYOUTS = {
    7: [[0.34, 0.16], [0.34, 0.5], [0.34, 0.84], [0.66, 0.16], [0.66, 0.5], [0.66, 0.84], [0.5, 0.33]],
    8: [[0.34, 0.14], [0.34, 0.5], [0.34, 0.86], [0.66, 0.14], [0.66, 0.5], [0.66, 0.86], [0.5, 0.32], [0.5, 0.68]],
    9: [[0.34, 0.13], [0.34, 0.36], [0.34, 0.64], [0.34, 0.87],
        [0.66, 0.13], [0.66, 0.36], [0.66, 0.64], [0.66, 0.87], [0.5, 0.5]],
    10: [[0.34, 0.12], [0.34, 0.37], [0.34, 0.63], [0.34, 0.88],
         [0.66, 0.12], [0.66, 0.37], [0.66, 0.63], [0.66, 0.88], [0.5, 0.245], [0.5, 0.755]]
  };

  const RANK_CYR = { 7: "7", 8: "8", 9: "9", 10: "10", 11: "В", 12: "Д", 13: "К", 14: "Т" };
  const RANK_LAT = { 7: "7", 8: "8", 9: "9", 10: "10", 11: "J", 12: "Q", 13: "K", 14: "A" };

  let indexMode = "cyr";
  try {
    indexMode = localStorage.getItem("pref_rank_mode") === "lat" ? "lat" : "cyr";
  } catch (e) { /* приватный режим */ }

  function isRed(suit) { return suit === 2 || suit === 3; }

  function rankLabel(rank) {
    return (indexMode === "lat" ? RANK_LAT : RANK_CYR)[rank] || String(rank);
  }

  function suitSvg(suit, extraClass) {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "suit" + (extraClass ? " " + extraClass : ""));
    svg.innerHTML = SUIT_PATHS[suit] || SUIT_PATHS[3];
    return svg;
  }

  /* --- фигурные карты: дама, король, валет --- */
  function courtSvg(rank, suit) {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 60 84");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "court");

    const headwear = {
      13: // король — корона с зубцами и усами
        '<path d="M19 27 L20 15 L25 21 L30 11 L35 21 L40 15 L41 27 Z" class="crown"/>' +
        '<rect x="18.5" y="25.5" width="23" height="3.2" rx="1.4" class="crown"/>' +
        '<circle cx="30" cy="10.5" r="1.7" class="gem"/>' +
        '<path d="M25.5 41.5 Q30 45.5 34.5 41.5 Q30 43.5 25.5 41.5 Z" class="court-face"/>',
      12: // дама — тиара и necklace
        '<path d="M21 28 C21 19 25 13 30 18 C35 13 39 19 39 28 Z" class="crown"/>' +
        '<circle cx="30" cy="16" r="1.9" class="gem"/>' +
        '<path d="M25 50 Q30 54 35 50" class="court-collar"/>',
      11: // валет — шляпа с пером
        '<path d="M20 28 C20 19 25 15 30 18 C35 15 40 19 40 28 Z" class="crown"/>' +
        '<path d="M37 24 C43 21 46 15 44 10 C41 13 38 18 37 24 Z" class="crown"/>' +
        '<path d="M25.5 41.5 Q30 45 34.5 41.5 Q30 43 25.5 41.5 Z" class="court-face"/>'
    }[rank];

    const pip = SUIT_PATHS[suit] || SUIT_PATHS[3];

    svg.innerHTML =
      '<path d="M5 7 H55 V77 H5 Z" class="court-frame"/>' +
      '<path d="M7.5 9.5 H52.5 V74.5 H7.5 Z" class="court-frame-inner"/>' +
      // плечи и корпус
      '<path d="M13 75 C14.5 58 21 49 30 49 C39 49 45.5 58 47 75 Z" class="court-body"/>' +
      // воротник-"V"
      '<path d="M24.5 50.5 L30 61 L35.5 50.5 L33 49.8 L30 56.5 L27 49.8 Z" class="court-collar"/>' +
      // голова
      '<ellipse cx="30" cy="37" rx="8.2" ry="9.2" class="court-face"/>' +
      // глаза
      '<circle cx="27" cy="36" r="0.85" class="court-eye"/>' +
      '<circle cx="33" cy="36" r="0.85" class="court-eye"/>' +
      headwear +
      // значок масти на груди
      '<g transform="translate(30 66) scale(0.52) translate(-12 -12)">' + pip + '</g>';
    return svg;
  }

  function corner(rank, suit) {
    const box = document.createElement("div");
    box.className = "idx";
    const r = document.createElement("span");
    r.className = "r";
    r.textContent = rankLabel(rank);
    box.appendChild(r);
    box.appendChild(suitSvg(suit));
    return box;
  }

  function pipsFace(rank, suit) {
    const wrap = document.createElement("div");
    wrap.className = "pips";
    const layout = PIP_LAYOUTS[rank] || [];
    layout.forEach(([x, y], index) => {
      const pip = suitSvg(suit);
      pip.classList.add("pip-dot");
      pip.style.left = (x * 100) + "%";
      pip.style.top = (y * 100) + "%";
      if (y > 0.55) pip.classList.add("flip");
      wrap.appendChild(pip);
    });
    return wrap;
  }

  /** Туз: только крупный значок масти по центру. */
  function aceFace(suit) {
    const wrap = document.createElement("div");
    wrap.className = "pips ace-face";
    const pip = suitSvg(suit);
    pip.classList.add("pip-dot");
    pip.style.left = "50%";
    pip.style.top = "50%";
    wrap.appendChild(pip);
    return wrap;
  }

  /**
   * Создаёт карту.
   * card = {id, suit, rank}; opts = {size: "lg|md|sm|xs", faceDown, cls, trump}
   */
  function makeCard(card, opts) {
    opts = opts || {};
    const node = document.createElement("div");
    node.className = "card" + (opts.size ? " s-" + opts.size : "");
    if (card && card.id !== undefined && card.id !== null) node.dataset.cid = String(card.id);

    if (opts.faceDown) {
      node.classList.add("back");
      return node;
    }

    const suit = card.suit;
    node.classList.add("suit-" + suit);
    if (opts.trump) node.classList.add("trump");

    const top = corner(card.rank, suit);
    top.classList.add("tl");
    const bottom = corner(card.rank, suit);
    bottom.classList.add("br");

    const face = document.createElement("div");
    face.className = "face";
    if (card.rank === 14) {
      face.appendChild(aceFace(suit));
    } else if (card.rank >= 11) {
      face.appendChild(courtSvg(card.rank, suit));
    } else {
      face.appendChild(pipsFace(card.rank, suit));
    }

    node.appendChild(top);
    node.appendChild(face);
    node.appendChild(bottom);
    return node;
  }

  function makeBack(opts) {
    return makeCard({ id: null, suit: 0, rank: 7 }, Object.assign({ faceDown: true }, opts || {}));
  }

  global.Cards = {
    makeCard,
    makeBack,
    suitSvg,
    courtSvg,
    isRed,
    rankLabel,
    get indexMode() { return indexMode; },
    setIndexMode(mode) {
      indexMode = mode === "lat" ? "lat" : "cyr";
      try { localStorage.setItem("pref_rank_mode", indexMode); } catch (e) { /* игнор */ }
      return indexMode;
    }
  };
})(window);
