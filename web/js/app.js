/* Преферанс — клиент. Одностраничник без сборки: работает в любом браузере. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ константы
  const SUIT_SYMBOL = ["♠", "♣", "♦", "♥"];
  const CONTRACT_SUITS = ["♠", "♣", "♦", "♥", "б/к"];
  const CONTRACT_NAMES = [];
  for (let n = 6; n <= 10; n++) {
    CONTRACT_NAMES.push(n + " пик", n + " треф", n + " бубн", n + " червей", n + " без козыря");
  }
  const STATUS_LABEL = {
    wait: "", pass: "пас", declarer: "заказчик", vist: "вист", mizer: "мизер", done: ""
  };
  const STATUS_CLASS = { pass: "pass", mizer: "mizer" };
  const STATUS_LABEL_PLAY = {
    wait: "", pass: "без виста", declarer: "заказчик", vist: "вист", mizer: "мизер", done: ""
  };

  // ------------------------------------------------------------------ состояние
  const state = {
    ws: null,
    playerId: null,
    roomCode: null,
    seat: -1,
    isHost: false,
    room: null,
    game: null,
    connected: false,
    reconnectTimer: null,
    reconnectDelay: 800,
    selected: new Set(),
    declareIndex: 0,
    withoutThree: false,
    lastPhase: null,
    screen: "home",
    lastTrick: null,
    lastTrickAt: 0,
    trickTimer: null,
    resuming: false,
    animSeen: new Set(),
    animRound: -1,
    handAnimKey: null,
    blindBid: false,
    auctionIndex: null,
    auctionKey: null,
    modalKind: null,
    mizerBlind: false,
    turnTimerEnd: 0
  };

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  // ------------------------------------------------------------------ хранилище
  function loadLocal() {
    try {
      state.playerId = localStorage.getItem("pref_player_id");
      if (!state.playerId) {
        state.playerId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now() + Math.random()));
        localStorage.setItem("pref_player_id", state.playerId);
      }
      state.roomCode = localStorage.getItem("pref_room_code");
    } catch (e) { /* приватный режим */ }
  }

  function saveRoom(code) {
    state.roomCode = code;
    try {
      if (code) localStorage.setItem("pref_room_code", code);
      else localStorage.removeItem("pref_room_code");
    } catch (e) { /* игнор */ }
  }

  // ------------------------------------------------------------------ экраны
  function showScreen(name) {
    state.screen = name;
    document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
    const node = $("screen-" + name);
    if (node) node.classList.add("active");
  }

  let toastTimer = null;
  function toast(text, isError) {
    const node = $("toast");
    node.textContent = text;
    node.classList.toggle("error", !!isError);
    node.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.remove("show"), 3200);
  }

  function setStatus(id, text) {
    const node = $(id);
    if (node) node.textContent = text || "";
  }

  // ------------------------------------------------------------------ таймер хода
  function updateTurnTimer() {
    const node = $("turn-timer");
    if (!node) return;
    const game = state.game;
    if (!game || !state.turnTimerEnd || game.turn === null || game.turn === undefined) {
      node.hidden = true;
      return;
    }
    const player = (game.players || [])[game.turn];
    if (!player || player.is_bot || game.phase === "round_end" || game.phase === "match_end") {
      node.hidden = true;
      return;
    }
    const left = Math.max(0, Math.ceil((state.turnTimerEnd - Date.now()) / 1000));
    const minutes = Math.floor(left / 60);
    const seconds = String(left % 60).padStart(2, "0");
    node.hidden = false;
    node.textContent = "⏱ " + minutes + ":" + seconds;
    node.classList.toggle("mine", game.turn === state.seat);
    node.classList.toggle("urgent", left <= 30);
  }

  function syncTurnTimer(game) {
    // Опираемся на серверное «осталось секунд», а не на абсолютные часы:
    // у клиента и сервера может различаться системное время.
    if (!game) {
      state.turnTimerEnd = 0;
    } else if (game.turn_time_left !== undefined && game.turn_time_left !== null) {
      state.turnTimerEnd = Date.now() + Number(game.turn_time_left) * 1000;
    } else if (game.turn_deadline) {
      state.turnTimerEnd = Number(game.turn_deadline) * 1000;
    } else {
      state.turnTimerEnd = 0;
    }
    updateTurnTimer();
  }

  // ------------------------------------------------------------------ сеть
  function wsUrl() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + "/ws";
  }

  function connect() {
    if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) return;
    const ws = new WebSocket(wsUrl());
    state.ws = ws;

    ws.onopen = () => {
      state.connected = true;
      state.reconnectDelay = 800;
      if (state.roomCode) {
        state.resuming = true;
        send({ type: "resume", code: state.roomCode, player_id: state.playerId });
      }
      render();
    };

    ws.onmessage = (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch (e) { return; }
      handleMessage(message);
    };

    ws.onclose = () => {
      state.connected = false;
      render();
      if (state.roomCode) {
        clearTimeout(state.reconnectTimer);
        state.reconnectTimer = setTimeout(connect, state.reconnectDelay);
        state.reconnectDelay = Math.min(state.reconnectDelay * 1.6, 8000);
      }
    };

    ws.onerror = () => { try { ws.close(); } catch (e) { /* игнор */ } };
  }

  function send(payload) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(payload));
      return true;
    }
    toast("Нет соединения с сервером", true);
    return false;
  }

  const CLIENT_VERSION = "2026-10-21-6";

  function handleMessage(message) {
    switch (message.type) {
      case "state":
        if (message.version && message.version !== CLIENT_VERSION && !state.versionWarned) {
          state.versionWarned = true;
          toast("Сервер работает со старой версией — перезапустите его (Ctrl+C, потом run.bat)", true);
        }
        state.room = message.room;
        state.seat = message.you;
        state.isHost = message.is_host;
        state.game = message.game;
        if (!state.game) showScreen("lobby");
        else showScreen("game");
        render();
        break;
      case "joined":
        saveRoom(message.room);
        state.seat = message.seat;
        if (state.resuming) {
          state.resuming = false;
          toast("Связь восстановлена — вы снова за столом");
        }
        break;
      case "notice":
        toast(message.text);
        break;
      case "error":
        toast(message.message || "Ошибка", true);
        Sound.play("error");
        break;
      case "resume_failed":
        saveRoom(null);
        showScreen("home");
        toast("Комната закрыта: сервер перезапустился или комната удалена", true);
        break;
      case "left":
        saveRoom(null);
        state.room = null;
        state.game = null;
        showScreen("home");
        break;
    }
  }

  // ------------------------------------------------------------------ главная
  function renderHome() {
    const name = $("input-name");
    if (name && !name.value) {
      try { name.value = localStorage.getItem("pref_name") || ""; } catch (e) { /* игнор */ }
    }
  }

  function playerName() {
    const input = $("input-name");
    const name = (input && input.value || "").trim().slice(0, 20) || "Игрок";
    try { localStorage.setItem("pref_name", name); } catch (e) { /* игнор */ }
    return name;
  }

  // ------------------------------------------------------------------ лобби
  function renderLobby() {
    if (!state.room) return;
    $("room-code").textContent = state.room.code;
    $("top-code").textContent = state.room.code;
    $("menu-room").textContent = "Комната " + state.room.code;

    const list = $("lobby-seats");
    list.innerHTML = "";
    (state.room.seats || []).forEach((seat, index) => {
      const row = el("div", "seat-row" + (seat ? "" : " empty"));
      if (seat) {
        const who = el("div", "who", seat.name + (seat.player_id === state.playerId ? " (вы)" : ""));
        row.appendChild(who);
        if (seat.is_bot) row.appendChild(el("span", "tag bot", "бот"));
        else row.appendChild(el("span", "tag" + (seat.connected ? "" : " off"), seat.connected ? "на связи" : "отключён"));
        if (!seat.is_bot && state.isHost) {
          const kick = el("button", "btn small ghost", "Убрать");
          kick.onclick = () => send({ type: "remove_bot", seat: index });
          row.appendChild(kick);
        }
      } else {
        row.appendChild(el("div", "who", "свободное место"));
        if (state.isHost) {
          const add = el("button", "btn small", "Добавить бота");
          add.onclick = () => send({ type: "add_bot" });
          row.appendChild(add);
        }
      }
      list.appendChild(row);
    });

    const options = state.room.options || {};
    document.querySelectorAll("#seg-variant button").forEach((b) => {
      b.classList.toggle("active", Number(b.dataset.value) === options.variant);
    });
    document.querySelectorAll("#seg-bullet button").forEach((b) => {
      b.classList.toggle("active", Number(b.dataset.value) === options.max_bullet);
    });
    document.querySelectorAll("#seg-blind button").forEach((b) => {
      b.classList.toggle("active", (Number(b.dataset.value) === 1) === !!options.blind);
    });

    const filled = (state.room.seats || []).every(Boolean);
    $("btn-start").disabled = !filled || !state.isHost;
    $("btn-add-bot").disabled = !state.isHost || filled;
    setStatus("lobby-status", filled ? "" : "Нужно трое игроков — добавьте бота.");
  }

  // ------------------------------------------------------------------ таблица
  function trumpOf(game) {
    if (!game || !game.contract) return null;
    return game.contract.trump;
  }

  function beats(candidate, current, trump, leadSuit) {
    const cTrump = trump !== null && trump !== undefined && trump !== 4 && candidate.suit === trump;
    const bTrump = trump !== null && trump !== undefined && trump !== 4 && current.suit === trump;
    if (cTrump !== bTrump) return cTrump;
    if (cTrump) return candidate.rank > current.rank;
    const lead = leadSuit !== null && leadSuit !== undefined ? leadSuit : current.suit;
    if (candidate.suit === lead && current.suit !== lead) return true;
    if (current.suit === lead && candidate.suit !== lead) return false;
    if (candidate.suit === current.suit) return candidate.rank > current.rank;
    return false;
  }

  function trickWinner(entries, game) {
    if (!entries || !entries.length) return null;
    const trump = trumpOf(game);
    const lead = game.lead_suit;
    let best = entries[0];
    for (let i = 1; i < entries.length; i++) {
      if (beats(entries[i].card, best.card, trump, lead)) best = entries[i];
    }
    return best;
  }

  // ------------------------------------------------------------------ игровой стол
  function renderGame() {
    const game = state.game;
    if (!game) {
      syncTurnTimer(null);
      return;
    }
    syncTurnTimer(game);
    if (state.modalKind === "mizer" &&
        !(game.phase === "auction" && game.turn === state.seat)) {
      closeModal();
    }

    if (game.phase !== state.lastPhase) {
      if (game.phase === "declare") {
        const me = (game.players || [])[state.seat];
        const base = (me && me.bid !== null && me.bid !== undefined) ? me.bid : (game.current_bid || 0);
        state.declareIndex = Math.max(0, Math.min(24, base));
        state.withoutThree = false;
      }
      if (game.phase === "drop") state.selected.clear();
      if (game.phase === "playing") Sound.play("deal");
    }

    $("top-code").textContent = (state.room && state.room.code) || "-----";
    $("top-round").textContent = "Раунд " + game.round;
    $("top-contract").textContent = game.contract
      ? game.contract.name + (game.without_three ? " · без 3 взяток" : "")
      : (game.round_type === "raspas" ? "Распасы" : (game.round_type === "mizer" ? "Мизер" : "Торг"));

    const players = game.players || [];
    const leftSeat = (state.seat + 1) % 3;
    const rightSeat = (state.seat + 2) % 3;
    renderOpponent($("slot-left"), players[leftSeat], leftSeat, game);
    renderOpponent($("slot-right"), players[rightSeat], rightSeat, game);
    renderScorebar(players, leftSeat, rightSeat, game);

    renderTalon(game);
    renderPlaque(game);
    renderTrick(game);
    $("center-hint").textContent = hintFor(game);

    renderMyInfo(game);
    renderHand(game);
    renderActions(game);
    renderLog(game);
  }

  function renderScorebar(players, leftSeat, rightSeat, game) {
    const bar = $("scorebar");
    bar.innerHTML = "";
    const order = [leftSeat, state.seat, rightSeat];
    order.forEach((seat) => {
      const player = players[seat];
      if (!player) return;
      const chip = el("div", "score-chip");
      if (game.turn === seat) chip.classList.add("turn");
      chip.appendChild(el("span", "sc-name", player.name + (seat === state.seat ? " (вы)" : "")));
      const track = el("span", "sc-bar");
      const fill = el("i");
      const percent = Math.min(100, (player.bullet / Math.max(1, game.max_bullet)) * 100);
      fill.style.width = percent + "%";
      track.appendChild(fill);
      chip.appendChild(track);
      const vists = el("span", "sc-vists" + (player.vists < 0 ? " neg" : ""), String(player.vists));
      chip.appendChild(vists);
      bar.appendChild(chip);
    });
  }

  function renderOpponent(container, player, seat, game) {
    container.innerHTML = "";
    if (!player) return;
    const box = el("div", "opponent");
    if (game.turn === seat) box.classList.add("turn");

    const avatar = el("div", "avatar", (player.name || "?").trim().charAt(0).toUpperCase());
    box.appendChild(avatar);
    box.appendChild(el("div", "nm", player.name));

    const afterAuction = ["playing", "round_end", "match_end"].indexOf(game.phase) >= 0;
    const labels = afterAuction ? STATUS_LABEL_PLAY : STATUS_LABEL;
    const status = labels[player.status] || "";
    box.appendChild(el("div", "stat", "взяток: " + player.tricks));
    if (status) {
      const badge = el("div", "badge " + (STATUS_CLASS[player.status] || ""), status);
      box.appendChild(badge);
    }
    if (game.declarer === seat && game.contract) {
      box.appendChild(el("div", "stat", "контракт: " + game.contract.name));
    }

    const mini = el("div", "mini-hand");
    const open = game.open_hands && game.open_hands_data && game.open_hands_data[String(seat)];
    if (open) {
      open.forEach((card) => {
        const m = el("div", "mini-card suit-" + card.suit);
        m.title = Cards.rankLabel(card.rank) + SUIT_SYMBOL[card.suit];
        mini.appendChild(m);
      });
    } else {
      const count = player.hand_count || 0;
      for (let i = 0; i < Math.min(count, 12); i++) mini.appendChild(el("div", "mini-card"));
    }
    box.appendChild(mini);
    container.appendChild(box);
  }

  function renderPlaque(game) {
    const plaque = $("plaque");
    plaque.innerHTML = "";
    if (game.contract) {
      const trump = game.contract.trump;
      plaque.appendChild(el("div", "pl-label", "контракт"));
      plaque.appendChild(el("div", "pl-name", game.contract.name));
      if (trump !== null && trump !== undefined && trump !== 4) {
        const suit = el("div", "pl-suit suit-" + trump, SUIT_SYMBOL[trump]);
        plaque.appendChild(suit);
      }
      if (game.without_three) plaque.appendChild(el("div", "pl-tag", "без 3 взяток"));
    } else if (game.round_type === "raspas") {
      plaque.appendChild(el("div", "pl-label", "игра"));
      plaque.appendChild(el("div", "pl-name", "Распасы"));
      plaque.appendChild(el("div", "pl-suit", "—"));
    } else if (game.round_type === "mizer") {
      plaque.appendChild(el("div", "pl-label", "игра"));
      plaque.appendChild(el("div", "pl-name", "Мизер"));
      plaque.appendChild(el("div", "pl-suit", "—"));
    } else {
      plaque.appendChild(el("div", "pl-label", "торг"));
      plaque.appendChild(el("div", "pl-name", game.current_bid_name || "открываем"));
    }
  }

  function renderTalon(game) {
    const zone = $("talon");
    zone.innerHTML = "";
    const talon = game.talon || [];
    if (!talon.length) {
      zone.hidden = true;
      return;
    }
    zone.hidden = false;
    zone.appendChild(el("div", "talon-label", "Прикуп"));
    talon.forEach((card) => {
      const node = Cards.makeCard(card, { size: "lg" });
      node.classList.add("talon-card");
      zone.appendChild(node);
    });
  }

  function renderMyInfo(game) {
    const box = $("my-info");
    box.innerHTML = "";
    const players = game.players || [];
    const me = players[state.seat];
    if (!me) return;
    if (game.turn === state.seat) box.classList.add("turn");
    else box.classList.remove("turn");

    box.appendChild(el("div", "avatar", (me.name || "?").trim().charAt(0).toUpperCase()));
    box.appendChild(el("div", "nm", me.name || "Вы"));
    box.appendChild(el("div", "stat", "взяток: " + me.tricks));
    const status = (["playing", "round_end", "match_end"].indexOf(game.phase) >= 0
      ? STATUS_LABEL_PLAY : STATUS_LABEL)[me.status] || "";
    if (status && status !== "заказчик") {
      box.appendChild(el("div", "stat", status));
    }
  }

  function renderTrick(game) {
    const trick = $("trick");
    trick.innerHTML = "";
    let entries = game.trick || [];
    let stale = false;

    if (!entries.length && state.lastTrick && Date.now() - state.lastTrickAt < 2200) {
      entries = state.lastTrick;
      stale = true;
    } else if (entries.length) {
      state.lastTrick = entries;
      state.lastTrickAt = Date.now();
      clearTimeout(state.trickTimer);
      state.trickTimer = setTimeout(() => {
        if (state.game) renderTrick(state.game);
      }, 2400);
    }

    // анимация проигрывается только для новых карт (иначе стол дёргается при каждом обновлении)
    if (state.animRound !== game.round) {
      state.animSeen = new Set();
      state.animRound = game.round;
    }

    const players = game.players || [];
    const winner = entries.length === 3 ? trickWinner(entries, game) : null;

    entries.forEach((entry) => {
      const slot = el("div", "trick-slot");
      const trump = trumpOf(game);
      const card = Cards.makeCard(entry.card, {
        size: "md",
        trump: trump !== null && trump !== undefined && trump !== 4 && entry.card.suit === trump
      });
      if (!state.animSeen.has(entry.card.id)) {
        card.classList.add("deal-in");
        state.animSeen.add(entry.card.id);
      }
      if (winner && winner.seat === entry.seat) card.classList.add("win");
      if (stale) card.style.opacity = ".5";
      slot.appendChild(card);
      slot.appendChild(el("div", "who", players[entry.seat] ? players[entry.seat].name : ""));
      trick.appendChild(slot);
    });
  }

  function renderHand(game) {
    const hand = $("hand");
    hand.innerHTML = "";
    const legal = new Set(game.legal || []);
    const dropping = game.can_drop;
    const handCards = game.hand || [];
    // Анимация раздачи — один раз на раздачу, а не на каждое обновление состояния.
    const handAnimKey = (state.roomCode || "") + ":" + game.round;
    const animateHand = state.handAnimKey !== handAnimKey;

    handCards.forEach((card, index) => {
      const trump = trumpOf(game);
      const isTrump = trump !== null && trump !== undefined && trump !== 4 && card.suit === trump;
      const hidden = card.blind || (game.phase === "auction" && !game.opened);
      const node = hidden
        ? Cards.makeCard({ id: card.id, suit: 0, rank: 7 }, { size: "lg", faceDown: true })
        : Cards.makeCard(card, { size: "lg", trump: isTrump });
      if (animateHand) {
        node.classList.add("dealing");
        node.style.animationDelay = (index * 45) + "ms";
      }
      if (hidden) node.title = "карта закрыта";
      if (dropping) {
        if (state.selected.has(card.id)) node.classList.add("selected");
        node.onclick = () => {
          if (state.selected.has(card.id)) state.selected.delete(card.id);
          else if (state.selected.size < 2) state.selected.add(card.id);
          else { toast("Нужно сбросить ровно две карты", true); return; }
          renderHand(game);
          renderActions(game);
        };
      } else if (game.can_play) {
        if (game.pending) {
          // ждём розыгрыша взятки
        } else if (!legal.has(card.id)) node.classList.add("illegal");
        else node.onclick = () => {
          Sound.play("play");
          send({ type: "play", card: card.id });
        };
      }
      hand.appendChild(node);
    });
    if (animateHand && handCards.length) state.handAnimKey = handAnimKey;
  }

  function hintFor(game) {
    if (game.turn === null || game.turn === undefined) return "";
    const players = game.players || [];
    const who = players[game.turn];
    const name = who ? who.name : "";
    switch (game.phase) {
      case "auction": return game.turn === state.seat ? "Ваш ход: назовите контракт или пасуйте" : "Ходит " + name;
      case "drop": return game.turn === state.seat ? "Выберите две карты для сброса" : "Сбрасывает " + name;
      case "declare": return game.turn === state.seat ? "Назначьте контракт" : "Назначает контракт " + name;
      case "whist": return game.turn === state.seat ? "Ваш ход: вист или пас" : "Отвечает " + name;
      case "catch_mizer": return game.turn === state.seat ? "Ловить мизер?" : name + " решает";
      case "playing":
        if (game.pending) return "Взятка разыгрывается…";
        return game.turn === state.seat ? "Выберите карту из руки" : "Ходит " + name;
      case "whist_mode": return game.turn === state.seat ? "Выберите: вслепую или открыто" : name + " выбирает режим виста";
      case "round_end": return "Раунд завершён";
      case "match_end": return "Матч завершён";
    }
    return "";
  }

  // ------------------------------------------------------------------ окна и таблица счёта
  function buildScoreTable(game) {
    const players = (game.players || []).slice().sort((a, b) => b.vists - a.vists);
    const table = el("table", "result score-table");
    const thead = el("thead");
    const hrow = el("tr");
    ["Игрок", "Взятки", "Пуля", "Гора", "Висты"].forEach((title) => {
      hrow.appendChild(el("th", null, title));
    });
    thead.appendChild(hrow);
    table.appendChild(thead);
    const tbody = el("tbody");
    const best = players.length ? players[0].vists : 0;
    players.forEach((player) => {
      const row = el("tr");
      if (player.vists === best) row.classList.add("win");
      const name = player.name + (player.seat === state.seat ? " (вы)" : "");
      row.appendChild(el("td", "name", name));
      row.appendChild(el("td", null, String(player.tricks)));
      row.appendChild(el("td", null, String(player.bullet)));
      row.appendChild(el("td", null, String(player.mountain)));
      row.appendChild(el("td", "vists " + (player.vists > 0 ? "pos" : player.vists < 0 ? "neg" : ""),
        String(player.vists)));
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    return table;
  }

  function openModal(title, body, kind) {
    state.modalKind = kind || null;
    $("modal-title").textContent = title;
    const holder = $("modal-body");
    holder.innerHTML = "";
    if (body) holder.appendChild(body);
    $("modal-layer").hidden = false;
  }

  function closeModal() {
    $("modal-layer").hidden = true;
    state.modalKind = null;
    state.mizerBlind = false;
  }

  function openMizerConfirm(blind) {
    state.mizerBlind = !!blind;
    const wrap = el("div");
    const copy = el("p", "modal-copy");
    copy.textContent = blind
      ? "Вы хотите объявить мизер вслепую. Карты останутся закрытыми до конца торгов, " +
        "а взять нельзя ни одной взятки."
      : "Вы хотите объявить мизер. Нужно не взять ни одной взятки за раздачу.";
    wrap.appendChild(copy);
    wrap.appendChild(el("p", "hint",
      "Мизер можно перебить заявкой на 9 взяток и выше."));
    const actions = el("div", "modal-actions");
    const cancel = el("button", "btn", "Отмена");
    cancel.onclick = () => closeModal();
    const confirm = el("button", "btn primary", "Взять мизер");
    confirm.onclick = () => {
      Sound.play("bid");
      send({ type: "bid", kind: "miser", blind: state.mizerBlind });
      closeModal();
    };
    actions.appendChild(cancel);
    actions.appendChild(confirm);
    wrap.appendChild(actions);
    openModal("Подтверждение мизера", wrap, "mizer");
  }

  function openScores() {
    if (!state.game) return;
    const wrap = el("div");
    wrap.appendChild(el("p", "hint",
      "Текущий счёт: пуля, гора и висты. Очко в пуле = 10 вистов."));
    wrap.appendChild(buildScoreTable(state.game));
    openModal("Таблица счёта", wrap, "scores");
  }

  // ------------------------------------------------------------------ действия
  function renderActions(game) {
    const box = $("actions");
    box.innerHTML = "";
    const mine = game.turn === state.seat;

    if (game.phase === "auction" && mine) {
      const closed = !game.opened;
      const available = (game.available_bids || []).slice().sort((a, b) => a - b);
      const key = [
        game.round, game.turn, game.current_bid, game.opened,
        game.can_bid_blind, available.join(",")
      ].join("|");
      if (state.auctionKey !== key) {
        state.auctionKey = key;
        state.auctionIndex = available.length ? available[0] : null;
      }
      if (state.auctionIndex === null || available.indexOf(state.auctionIndex) < 0) {
        state.auctionIndex = available.length ? available[0] : null;
      }

      const picker = el("div", "bid-picker");
      const stepper = el("div", "stepper");
      const minus = el("button", "btn", "−");
      const index = state.auctionIndex;
      const pos = index === null ? -1 : available.indexOf(index);
      minus.disabled = pos <= 0;
      minus.onclick = () => {
        if (pos > 0) {
          state.auctionIndex = available[pos - 1];
          renderActions(game);
        }
      };
      const plus = el("button", "btn", "+");
      plus.disabled = pos < 0 || pos >= available.length - 1;
      plus.onclick = () => {
        if (pos >= 0 && pos < available.length - 1) {
          state.auctionIndex = available[pos + 1];
          renderActions(game);
        }
      };
      const value = el("div", "value");
      if (index === null) {
        value.textContent = "нет ставок";
      } else {
        value.appendChild(el("span", "n", String(6 + Math.floor(index / 5))));
        value.appendChild(el("span", "s suit-" + (index % 5), CONTRACT_SUITS[index % 5]));
        value.title = CONTRACT_NAMES[index];
      }
      stepper.appendChild(minus);
      stepper.appendChild(value);
      stepper.appendChild(plus);
      picker.appendChild(stepper);
      if (available.length > 1) {
        picker.appendChild(el("div", "hint",
          "Ставка " + (pos + 1) + " из " + available.length + " доступных"));
      }
      box.appendChild(picker);

      if (closed) {
        const hint = game.can_bid_blind
          ? "У вас закрытые карты. Можно заявить контракт вслепую, " +
            "взять мизер вслепую или открыть карты и торговаться как обычно."
          : "Слепую заявку сейчас перебить нельзя — сначала откройте карты.";
        box.appendChild(el("div", "hint", hint));
      }

      const row = el("div", "bid-actions");
      const bid = el("button", "btn primary", "Сделать ставку");
      bid.disabled = index === null || (closed && !game.can_bid_blind);
      bid.onclick = () => {
        if (index === null) return;
        Sound.play("bid");
        send({ type: "bid", kind: "contract", contract: index, blind: closed });
      };
      row.appendChild(bid);

      const pass = el("button", "btn", "Пас");
      pass.onclick = () => { Sound.play("bid"); send({ type: "bid", kind: "pass" }); };
      row.appendChild(pass);

      if (game.can_miser) {
        const miser = el("button", "btn", closed ? "Мизер вслепую" : "Мизер");
        miser.onclick = () => openMizerConfirm(closed);
        row.appendChild(miser);
      }

      if (game.can_open) {
        const open = el("button", "btn primary", "Открыть карты");
        open.onclick = () => { Sound.play("deal"); send({ type: "open_cards" }); };
        row.appendChild(open);
      }
      box.appendChild(row);
    }

    if (game.phase === "drop" && mine) {
      const info = el("div", "hint", "Выбрано: " + state.selected.size + " из 2");
      box.appendChild(info);
      const drop = el("button", "btn primary", "Сбросить две карты");
      drop.disabled = state.selected.size !== 2;
      drop.onclick = () => {
        Sound.play("deal");
        send({ type: "drop", cards: Array.from(state.selected) });
        state.selected.clear();
      };
      box.appendChild(drop);
    }

    if (game.phase === "declare" && mine) {
      const stepper = el("div", "stepper");
      const minus = el("button", "btn", "−");
      const value = el("div", "value", CONTRACT_NAMES[state.declareIndex]);
      const plus = el("button", "btn", "+");
      minus.onclick = () => { state.declareIndex = Math.max(0, state.declareIndex - 1); renderActions(game); };
      plus.onclick = () => { state.declareIndex = Math.min(24, state.declareIndex + 1); renderActions(game); };
      stepper.appendChild(minus);
      stepper.appendChild(value);
      stepper.appendChild(plus);
      box.appendChild(stepper);

      const w3 = el("button", "btn" + (state.withoutThree ? " primary" : ""), "Без 3 взяток");
      w3.onclick = () => { state.withoutThree = !state.withoutThree; renderActions(game); };
      box.appendChild(w3);

      const ok = el("button", "btn primary", "ОК");
      ok.onclick = () => { Sound.play("bid"); send({ type: "declare", contract: state.declareIndex, without_three: state.withoutThree }); };
      box.appendChild(ok);
    }

    if (game.phase === "whist" && mine) {
      const options = game.whist_options || ["pass", "vist"];
      const labels = { pass: "Пас", vist: "Вист", half: "Полвиста" };
      options.forEach((kind) => {
        const btn = el("button", "btn", labels[kind] || kind);
        btn.onclick = () => { Sound.play("bid"); send({ type: "whist", kind: kind }); };
        box.appendChild(btn);
      });
    }

    if (game.phase === "whist_mode" && mine) {
      const dark = el("button", "btn", "В тёмную (ставки ×2)");
      dark.onclick = () => send({ type: "whist_mode", dark: true });
      const light = el("button", "btn", "В светлую");
      light.onclick = () => send({ type: "whist_mode", dark: false });
      box.appendChild(dark);
      box.appendChild(light);
    }

    if (game.phase === "catch_mizer" && mine) {
      const yes = el("button", "btn primary", "Ловить мизер");
      yes.onclick = () => send({ type: "catch_mizer", accept: true });
      const no = el("button", "btn", "Не ловить");
      no.onclick = () => send({ type: "catch_mizer", accept: false });
      box.appendChild(yes);
      box.appendChild(no);
    }

    if (game.phase === "round_end" || game.phase === "match_end") {
      const btn = el("button", "btn primary", "Результаты");
      btn.onclick = () => showScreen("result");
      box.appendChild(btn);
    }
  }

  function renderLog(game) {
    const box = $("log");
    box.innerHTML = "";
    (game.log || []).slice(-40).forEach((line) => box.appendChild(el("div", null, line)));
    box.scrollTop = box.scrollHeight;
  }

  // ------------------------------------------------------------------ результаты
  function renderResult() {
    const game = state.game;
    if (!game) return;
    const body = $("result-body");
    body.innerHTML = "";

    const isEnd = game.phase === "match_end";
    $("result-title").textContent = isEnd ? "Матч завершён" : "Раунд завершён";
    $("btn-next-round").style.display = isEnd ? "none" : "";
    $("btn-next-round").onclick = () => {
      send({ type: "next_round" });
      showScreen("game");
    };
    const oldAgain = $("btn-again");
    if (oldAgain) oldAgain.remove();
    if (isEnd) {
      const again = el("button", "btn primary wide", "Новая игра");
      again.id = "btn-again";
      again.onclick = () => send({ type: "new_match" });
      $("btn-next-round").parentNode.insertBefore(again, $("btn-next-round").nextSibling);
    }

    const last = game.last_result;
    if (last) {
      const head = el("div", "hint");
      head.textContent = "Контракт: " + (last.contract || "—");
      body.appendChild(head);
      const lines = el("div", "result-lines");
      (last.lines || []).forEach((line) => lines.appendChild(el("div", null, line)));
      body.appendChild(lines);
    }

    body.appendChild(buildScoreTable(game));

    const note = el("div", "hint",
      "Вариант: " + game.variant_name + " · длина пули " + game.max_bullet +
      ". Очко в пуле = 10 вистов. Контракт N взяток даёт (N−5)×2 очка в пулю, " +
      "каждая недобранная взятка — (N−5)×2 в гору (вариант ×2 в Ленинграде).");
    body.appendChild(note);
  }

  // ------------------------------------------------------------------ конфетти
  function confetti() {
    const canvas = $("confetti");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    canvas.style.display = "block";
    const colors = ["#f2c14e", "#e2564f", "#6fd08c", "#7fb3ff", "#ffffff"];
    const pieces = [];
    for (let i = 0; i < 120; i++) {
      pieces.push({
        x: Math.random() * canvas.width,
        y: -20 - Math.random() * canvas.height * .5,
        w: 6 + Math.random() * 6,
        h: 9 + Math.random() * 8,
        vy: 1.4 + Math.random() * 2.4,
        vx: -1 + Math.random() * 2,
        rot: Math.random() * 6,
        vr: -.12 + Math.random() * .24,
        color: colors[Math.floor(Math.random() * colors.length)]
      });
    }
    let frames = 0;
    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      pieces.forEach((p) => {
        p.x += p.vx; p.y += p.vy; p.rot += p.vr;
        if (p.y > canvas.height + 30) { p.y = -20; p.x = Math.random() * canvas.width; }
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rot);
        ctx.fillStyle = p.color;
        ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
        ctx.restore();
      });
      frames++;
      if (frames < 220) requestAnimationFrame(draw);
      else canvas.style.display = "none";
    }
    requestAnimationFrame(draw);
  }

  // ------------------------------------------------------------------ правила
  const RULES_HTML = `
    <h3>Суть</h3>
    <p>Играют трое. Колода 32 карты (7–А в четырёх мастях), каждому по 10 карт,
    прикуп — 2 карты. Всего разыгрывается 10 взяток.</p>

    <h3>Торг</h3>
    <p>Игроки по очереди (от сдатчика) называют контракт или пасуют. Заявка должна быть
    выше предыдущей. Лестница контрактов — 25 штук:</p>
    <p><b>6 пик → 6 треф → 6 бубн → 6 червей → 6 без козыря → 7 пик → … → 10 без козыря.</b></p>
    <p>Козырь — это масть контракта. Торг заканчивается, когда все, кроме одного игрока,
    спасуют. Если пасуют все трое — играются распасы (без козыря, каждый играет за себя
    и старается взять как можно меньше взяток).</p>
    <p>Отдельно можно взять <b>мизер</b> — не взять ни одной взятки. Мизер доступен,
    пока текущая заявка не выше 8 взяток.</p>

    <h3>Прикуп и контракт</h3>
    <p>Победитель торга берёт обе карты прикупа и сбрасывает две ненужные (никто их не видит).
    Затем назначает контракт — не ниже своей заявки. Дополнительно можно взять
    <b>«без 3 взяток»</b>: пообещать взять меньше трёх взяток.</p>

    <h3>Вист</h3>
    <p>После назначения контракта соперники по очереди отвечают: <b>вист</b> или <b>пас</b>.
    Вистующий обязан взять своё число взяток, иначе платит штраф. Для контрактов 6 и 7
    доступен <b>полвиста</b> (вдвое меньше).</p>
    <table>
      <tr><th>Контракт</th><th>Взяток висту</th><th>Висты</th></tr>
      <tr><td>6</td><td>4</td><td>8</td></tr>
      <tr><td>7</td><td>2</td><td>8</td></tr>
      <tr><td>8</td><td>1</td><td>6</td></tr>
      <tr><td>9</td><td>1</td><td>8</td></tr>
      <tr><td>10</td><td>1</td><td>10</td></tr>
    </table>

    <h3>Взятки</h3>
    <p>Ходить нужно в масть, если она есть; иначе — козырем; если нет и козыря — любой картой.
    Взятку берёт старшая карта масти (или старший козырь). Победитель взятки ходит следующим.</p>

    <h3>Очки</h3>
    <p>У каждого игрока есть <b>пуля</b> (своя дорожка очков), <b>гора</b> (долг) и <b>висты</b>
    (счёт матча).</p>
    <ul>
      <li>Сыгранный контракт N взяток: <b>(N−5)×2</b> очка пишутся в вашу же пулю. Очко в пуле = <b>10 вистов</b>.</li>
      <li>Недобранная взятка: <b>(N−5)×2</b> (в варианте «Ленинград» ×2) очка в гору, соперникам идут очки в их пули.</li>
      <li>Вист: успех — висты по таблице выше, провал — очки в гору, заказчик получает компенсацию в свою пулю.
      Если вистуют оба соперника, каждый рассчитывается отдельно.</li>
      <li>Мизер: сыгран — 10 очков в пулю; каждая взятая взятка — 10 в гору.</li>
      <li>Распасы: каждая взятка — очко в гору (штраф растёт: 1, 2, 3), кто не взял ни одной — пишет очко в свою пулю.
      Любой сыгранный контракт сбрасывает серию распасов (амнистия).</li>
    </ul>
    <p><b>Конец матча:</b> в варианте «Сочи» — когда у всех пуля заполнена; в «Ленинграде» — когда
    сумма очков в пулях всех игроков не меньше длины пули × 3. Побеждает тот, у кого больше вистов.
    Висты могут быть отрицательными — это долг игрока.</p>

    <h3>Управление</h3>
    <p>Все действия — мышью или касанием. Если связь пропала, игра не сломается: клиент
    переподключится сам и продолжит с того же места.</p>
  `;

  function renderRules() {
    $("rules-body").innerHTML = RULES_HTML;
  }

  // ------------------------------------------------------------------ шпаргалка
  const cheatState = { tab: "hand", hand: [] };

  function cheatCards() {
    // полная колода: 4 масти × 8 рангов
    const cards = [];
    for (let suit = 0; suit < 4; suit++) {
      for (const rank of [7, 8, 9, 10, 11, 12, 13, 14]) {
        cards.push({ id: suit * 100 + rank, suit, rank });
      }
    }
    return cards;
  }

  function renderCheats() {
    const body = $("cheat-body");
    body.innerHTML = "";
    document.querySelectorAll("#cheat-tabs button").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === cheatState.tab);
    });

    if (cheatState.tab === "combos") {
      const note = el("p", "hint", "Сколько взяток набирает комбинация в среднем. " +
        "«Маленькие» — это 7, 8, 9, 10.");
      body.appendChild(note);
      const table = el("table", "result cheat-table");
      const thead = el("thead");
      const hrow = el("tr");
      ["Комбинация", "Взяток"].forEach((t) => hrow.appendChild(el("th", null, t)));
      thead.appendChild(hrow);
      table.appendChild(thead);
      const tbody = el("tbody");
      Cheat.COMBOS.forEach((combo) => {
        const row = el("tr");
        row.appendChild(el("td", "name", combo.text));
        row.appendChild(el("td", null, combo.range ? combo.range.join("–") : String(combo.tricks)));
        tbody.appendChild(row);
      });
      table.appendChild(tbody);
      body.appendChild(table);
      return;
    }

    if (cheatState.tab === "holes") {
      const note = el("p", "hint", "Если у мизериста в масти нет указанных карт — «дыра». " +
        "Вероятность поймать мизера по дыре:");
      body.appendChild(note);
      const table = el("table", "result cheat-table");
      const thead = el("thead");
      const hrow = el("tr");
      ["Дыра", "Вероятность"].forEach((t) => hrow.appendChild(el("th", null, t)));
      thead.appendChild(hrow);
      table.appendChild(thead);
      const tbody = el("tbody");
      Cheat.HOLES.forEach((hole) => {
        const row = el("tr");
        row.appendChild(el("td", "name", hole.text));
        row.appendChild(el("td", null, hole.note));
        tbody.appendChild(row);
      });
      table.appendChild(tbody);
      body.appendChild(table);
      const clean = el("p", "hint", "«Чистый» мизер — у него в каждой масти набор: 7, " +
        "(8 или 9), (10 или Валет), (Дама или Король), Туз. Тогда дыр нет и поймать его почти невозможно.");
      body.appendChild(clean);
      return;
    }

    // вкладка «по моей руке»
    const note = el("p", "hint", "Отметьте свои карты — покажем, сколько взяток они набирают " +
      "и в какой масти у мизериста дыра.");
    body.appendChild(note);

    const grid = el("div", "cheat-grid");
    cheatCards().forEach((card) => {
      const picked = cheatState.hand.some((c) => c.id === card.id);
      const node = Cards.makeCard(card, { size: "xs" });
      if (picked) node.classList.add("picked");
      node.onclick = () => {
        const index = cheatState.hand.findIndex((c) => c.id === card.id);
        if (index >= 0) cheatState.hand.splice(index, 1);
        else cheatState.hand.push(card);
        renderCheats();
      };
      grid.appendChild(node);
    });
    body.appendChild(grid);

    const clear = el("button", "btn small", "Очистить");
    clear.onclick = () => { cheatState.hand = []; renderCheats(); };
    body.appendChild(clear);

    if (!cheatState.hand.length) {
      body.appendChild(el("p", "hint", "Пока ничего не отмечено."));
      return;
    }

    const matched = Cheat.matchCombos(cheatState.hand);
    const result = el("div", "cheat-result");
    if (matched.length) {
      const best = matched[0];
      // несколько тузов считаем отдельно: каждый туз — это взятка
      const aces = cheatState.hand.filter((c) => c.rank === 14).length;
      const extra = Math.max(0, aces - (best.ranks.indexOf(14) >= 0 ? 1 : 0));
      const tricks = best.tricks + extra;
      const head = el("div", "cheat-big");
      head.textContent = "Ожидаем " + (best.range
        ? (best.range[0] + extra) + "–" + (best.range[1] + extra)
        : tricks) + " взяток";
      result.appendChild(head);
      result.appendChild(el("div", "hint", "Лучшее совпадение: " + best.text
        + (extra ? " (+" + extra + " за лишние тузы)" : "")));
      const list = el("div", "cheat-list");
      matched.slice(0, 6).forEach((combo) => {
        const row = el("div", "cheat-row");
        row.appendChild(el("span", null, combo.text));
        row.appendChild(el("b", null, combo.range ? combo.range.join("–") : String(combo.tricks)));
        list.appendChild(row);
      });
      result.appendChild(list);
    } else {
      result.appendChild(el("div", "hint", "Подходящих комбинаций в таблице нет — рука слабая."));
    }

    const analysis = Cheat.holeAnalysis(cheatState.hand);
    if (analysis.perSuit.some((s) => s.found.length)) {
      const h = el("div", "cheat-holes");
      h.appendChild(el("div", "cheat-big", "Ловля мизера"));
      analysis.perSuit.forEach((entry) => {
        if (!entry.found.length) return;
        const names = ["♠ пики", "♣ трефы", "♦ бубны", "♥ черви"];
        const line = el("div", "cheat-row");
        line.appendChild(el("span", null, names[entry.suit] + ": дыра " + entry.found[0].hole.text));
        line.appendChild(el("b", null, entry.found[0].hole.note));
        h.appendChild(line);
      });
      if (analysis.best) {
        const names = ["пики", "трефы", "бубны", "черви"];
        h.appendChild(el("div", "hint", "Лучшая дыра: " + names[analysis.best.suit] +
          " — " + analysis.best.hole.text + " (" + analysis.best.hole.note + ")"));
      }
      result.appendChild(h);
    } else {
      result.appendChild(el("div", "hint", "Дыр по вашей руке не видно."));
    }
    body.appendChild(result);
  }

  // ------------------------------------------------------------------ рендер
  function render() {
    // справочные экраны не переключаем при обновлениях состояния
    if (["rules", "cheats", "menu"].indexOf(state.screen) >= 0) return;
    if (!state.room) {
      showScreen("home");
      renderHome();
      return;
    }
    if (!state.game) {
      showScreen("lobby");
      renderLobby();
      return;
    }
    showScreen("game");
    renderGame();
    if (state.game.phase === "round_end" || state.game.phase === "match_end") {
      if (state.lastPhase !== state.game.phase || !$("screen-result").classList.contains("active")) {
        renderResult();
        showScreen("result");
        if (state.game.phase === "match_end") {
          const me = (state.game.players || [])[state.seat];
          const best = (state.game.players || []).reduce((a, b) => (b.vists > a.vists ? b : a), { vists: -1e9 });
          if (me && me.vists === best.vists) { Sound.play("win"); confetti(); }
          else Sound.play("lose");
        } else {
          Sound.play("trick");
        }
      }
    }
    state.lastPhase = state.game.phase;
  }

  // ------------------------------------------------------------------ события
  function bind() {
    $("btn-create").onclick = () => {
      send({ type: "create", name: playerName(), player_id: state.playerId, options: { variant: 1, max_bullet: 30, blind: true } });
    };
    $("btn-join").onclick = () => {
      const code = ($("input-code").value || "").trim().toUpperCase();
      if (code.length < 4) { toast("Введите код комнаты", true); return; }
      send({ type: "join", code: code, name: playerName(), player_id: state.playerId });
    };
    $("input-code").addEventListener("keydown", (e) => {
      if (e.key === "Enter") $("btn-join").click();
    });
    $("btn-quick").onclick = () => {
      if (state.room) send({ type: "leave" });
      send({ type: "create", name: playerName(), player_id: state.playerId, options: { variant: 1, max_bullet: 30, blind: true } });
      setTimeout(() => {
        send({ type: "add_bot" });
        setTimeout(() => {
          send({ type: "add_bot" });
          setTimeout(() => send({ type: "start" }), 250);
        }, 150);
      }, 300);
    };
    $("btn-rules").onclick = () => { renderRules(); showScreen("rules"); };
    $("btn-cheat").onclick = () => { renderCheats(); showScreen("cheats"); };
    $("btn-cheat-fab").onclick = () => { renderCheats(); showScreen("cheats"); };
    $("btn-menu-cheat").onclick = () => { renderCheats(); showScreen("cheats"); };
    $("btn-cheat-back").onclick = () => showScreen(state.room ? (state.game ? "game" : "lobby") : "home");
    document.querySelectorAll("#cheat-tabs button").forEach((btn) => {
      btn.onclick = () => { cheatState.tab = btn.dataset.tab; renderCheats(); };
    });
    $("btn-rules-back").onclick = () => showScreen(state.room ? (state.game ? "game" : "lobby") : "home");

    $("btn-copy").onclick = () => {
      const code = state.room ? state.room.code : "";
      if (navigator.clipboard) navigator.clipboard.writeText(code);
      else {
        const tmp = document.createElement("textarea");
        tmp.value = code; document.body.appendChild(tmp); tmp.select();
        try { document.execCommand("copy"); } catch (e) { /* игнор */ }
        document.body.removeChild(tmp);
      }
      toast("Код " + code + " скопирован");
    };
    $("btn-add-bot").onclick = () => send({ type: "add_bot" });
    $("btn-leave-room").onclick = () => send({ type: "leave" });
    $("btn-start").onclick = () => send({ type: "start" });

    document.querySelectorAll("#seg-variant button").forEach((btn) => {
      btn.onclick = () => send({ type: "settings", variant: Number(btn.dataset.value) });
    });
    document.querySelectorAll("#seg-bullet button").forEach((btn) => {
      btn.onclick = () => send({ type: "settings", max_bullet: Number(btn.dataset.value) });
    });
    document.querySelectorAll("#seg-blind button").forEach((btn) => {
      btn.onclick = () => send({ type: "settings", blind: Number(btn.dataset.value) === 1 });
    });

    $("btn-menu").onclick = () => {
      $("menu-room").textContent = "Комната " + (state.room ? state.room.code : "—");
      document.querySelectorAll("#seg-rankmode button").forEach((b) => {
        b.classList.toggle("active", b.dataset.value === Cards.indexMode);
      });
      showScreen("menu");
    };
    document.querySelectorAll("#seg-rankmode button").forEach((btn) => {
      btn.onclick = () => {
        Cards.setIndexMode(btn.dataset.value);
        document.querySelectorAll("#seg-rankmode button").forEach((b) => {
          b.classList.toggle("active", b.dataset.value === Cards.indexMode);
        });
        if (state.game) renderGame();
        if (state.game && (state.game.phase === "round_end" || state.game.phase === "match_end")) renderResult();
      };
    });
    $("btn-menu-resume").onclick = () => showScreen(state.game ? "game" : "lobby");
    $("btn-menu-rules").onclick = () => { renderRules(); showScreen("rules"); };
    $("btn-menu-leave").onclick = () => send({ type: "leave" });
    $("btn-result-menu").onclick = () => { send({ type: "leave" }); };

    $("btn-sound").onclick = () => {
      const on = Sound.toggle();
      $("btn-sound").classList.toggle("off", !on);
      $("btn-sound").textContent = on ? "♪" : "×";
    };

    $("log-head").onclick = () => $("log-box").classList.toggle("collapsed");
    $("btn-scores").onclick = openScores;
    $("modal-close").onclick = closeModal;
    $("modal-layer").onclick = (event) => {
      if (event.target === $("modal-layer")) closeModal();
    };
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !$("modal-layer").hidden) closeModal();
    });
  }

  // ------------------------------------------------------------------ старт
  loadLocal();
  bind();
  renderRules();
  renderHome();
  showScreen("home");
  $("btn-sound").classList.toggle("off", !Sound.enabled);
  $("btn-sound").textContent = Sound.enabled ? "♪" : "×";
  setInterval(updateTurnTimer, 250);
  connect();

  window.addEventListener("online", () => { if (!state.connected) connect(); });

  // отладочный доступ к состоянию (используется автотестами)
  window.__pref = state;
})();
