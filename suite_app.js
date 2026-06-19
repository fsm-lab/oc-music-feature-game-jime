(() => {
  "use strict";

  const APP_VERSION = "2026-06-14.feature-probe.rank-dnd.loudnorm.v3";
  const CLIP_VERSION = "loudnorm-20260614-01";
  const labels = ["A", "B", "C", "D"];
  const roundData = window.MUSIC_MATCH_DATA || { rounds: window.MUSIC_MATCH_ROUNDS || [], roundsPerSession: 4 };
  const allRounds = roundData.rounds || [];
  const roundsPerSession = Number(roundData.roundsPerSession || 4);

  const variants = [
    {
      id: "rank4",
      name: "近い順ならべ",
      short: "A-Dを近い順にする",
      detail: "お手本を聞いて、4つの候補を近い順に並べる形式。1回で4候補すべての順位が残ります。"
    },
    {
      id: "best_card",
      name: "一番近いもの",
      short: "A-Dから1つ選ぶ",
      detail: "操作が一番少ない形式。短時間で多くの人に回しやすい。"
    },
    {
      id: "duel",
      name: "2択対決",
      short: "2つずつ選ぶ",
      detail: "迷いにくい二択形式。直接勝敗を集められる。"
    },
    {
      id: "rating",
      name: "点数つけ",
      short: "1-5点をつける",
      detail: "どれも似ていない/どれも似ているという絶対評価を残せる。"
    },
    {
      id: "keep_drop",
      name: "残す・外す",
      short: "使えそうなら残す",
      detail: "候補を取捨選択する目的に直結する。複数候補を残せる。"
    }
  ];

  const state = {
    collectionMode: detectMode(),
    variantId: "rank4",
    sessionId: "",
    participantCode: "",
    ageGroup: "",
    startedAt: 0,
    roundStartedAt: 0,
    currentRound: 0,
    sessionRounds: [],
    score: 0,
    confidence: "not_asked",
    trial: null,
    responses: [],
    events: [],
    playCounts: {},
    seed: "",
    isFinishingRound: false,
    isFinished: false
  };

  const $ = (id) => document.getElementById(id);
  let timerId = null;
  let touchDrag = null;

  function detectMode() {
    const params = new URLSearchParams(window.location.search);
    const mode = params.get("mode") || window.SUITE_COLLECTION_MODE || "";
    if (mode === "public" || window.location.pathname.includes("public")) return "public";
    return "test";
  }

  function init() {
    applyLayoutMode();
    if (!allRounds.length) {
      $("variantSummary").textContent = "カードデータを読み込めませんでした。cards_2sec.js を確認してください。";
      $("startBtn").disabled = true;
      return;
    }
    renderWaveArt();
    bindLayoutModeWatcher();
    const variantSelect = $("variantSelect");
    variants.forEach((variant) => {
      const option = document.createElement("option");
      option.value = variant.id;
      option.textContent = `${variant.name}: ${variant.short}`;
      variantSelect.appendChild(option);
    });
    variantSelect.value = "rank4";
    variantSelect.addEventListener("change", () => {
      state.variantId = variantSelect.value;
      renderVariantSummary();
    });
    state.variantId = variantSelect.value;
    renderMode();
    renderVariantSummary();
    $("startBtn").addEventListener("click", startGame);
    $("nextBtn").addEventListener("click", finishRound);
    $("quitBtn").addEventListener("click", finishGame);
    $("againBtn").addEventListener("click", resetToIntro);
    $("downloadJsonBtn").addEventListener("click", async () => {
      const payload = buildPayload(true);
      download(`${state.sessionId}.json`, JSON.stringify(payload, null, 2), "application/json");
    });
    $("downloadCsvBtn").addEventListener("click", () => download(`${state.sessionId}.csv`, buildCsv(), "text/csv;charset=utf-8"));
    document.querySelectorAll("[data-confidence]").forEach((button) => {
      button.addEventListener("click", () => setConfidence(button.dataset.confidence));
    });
  }

  function renderWaveArt() {
    const root = document.querySelector(".wave-art");
    root.innerHTML = "";
    for (let i = 0; i < 24; i += 1) {
      const bar = document.createElement("i");
      bar.style.setProperty("--h", String(18 + Math.round(Math.abs(Math.sin(i * 0.72)) * 68)));
      root.appendChild(bar);
    }
  }

  function renderMode() {
    const badge = $("modeBadge");
    badge.className = state.collectionMode;
    badge.textContent = state.collectionMode === "public" ? "公開モード: 本番ログ" : "テストモード: 検証ログ";
    const switcher = $("modeSwitch");
    if (state.collectionMode === "public") {
      switcher.hidden = true;
      switcher.removeAttribute("href");
      switcher.textContent = "";
    } else {
      switcher.hidden = false;
      switcher.href = "suite.html?mode=public";
      switcher.textContent = "公開モードへ";
    }
  }

  function applyLayoutMode() {
    const params = new URLSearchParams(window.location.search);
    const mobileQuery = window.matchMedia?.("(max-width: 720px), (pointer: coarse)")?.matches || false;
    const mobileLayout = window.SUITE_MOBILE_LAYOUT || params.get("layout") === "mobile" || window.location.pathname.includes("mobile") || mobileQuery;
    document.body.classList.toggle("mobile-layout", Boolean(mobileLayout));
  }

  function bindLayoutModeWatcher() {
    const query = window.matchMedia?.("(max-width: 720px), (pointer: coarse)");
    if (!query) return;
    const update = () => applyLayoutMode();
    if (query.addEventListener) query.addEventListener("change", update);
    else if (query.addListener) query.addListener(update);
  }

  function renderVariantSummary() {
    const variant = getVariant();
    $("variantSummary").innerHTML = `<b>${escapeHtml(variant.name)}</b><br>${escapeHtml(variant.detail)}<br><br><b>記録:</b> 順位、時間、再生回数、内部候補ID、特徴量メタデータを保存。`;
  }

  function getVariant() {
    return variants.find((variant) => variant.id === state.variantId) || variants[0];
  }

  function shuffle(items) {
    const copy = items.slice();
    for (let i = copy.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
  }

  function hashSeed(text) {
    let hash = 2166136261;
    for (let i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function seededRandom(seedText) {
    let stateValue = hashSeed(seedText) || 1;
    return () => {
      stateValue ^= stateValue << 13;
      stateValue ^= stateValue >>> 17;
      stateValue ^= stateValue << 5;
      return ((stateValue >>> 0) / 4294967296);
    };
  }

  function weightedPick(pool, rng) {
    const total = pool.reduce((sum, round) => sum + Math.max(0.1, Number(round.priorityWeight || 1)), 0);
    let cursor = rng() * total;
    for (let index = 0; index < pool.length; index += 1) {
      cursor -= Math.max(0.1, Number(pool[index].priorityWeight || 1));
      if (cursor <= 0) return index;
    }
    return pool.length - 1;
  }

  function chooseSessionRounds(seedText) {
    const rng = seededRandom(seedText);
    const pool = allRounds.slice();
    const selected = [];
    while (pool.length && selected.length < Math.min(roundsPerSession, allRounds.length)) {
      const index = weightedPick(pool, rng);
      selected.push(pool.splice(index, 1)[0]);
    }
    return selected;
  }

  function makeId(prefix) {
    const bytes = new Uint32Array(2);
    crypto.getRandomValues(bytes);
    return `${prefix}-${Date.now().toString(36)}-${Array.from(bytes).map((v) => v.toString(36)).join("")}`;
  }

  function formatTime(ms) {
    const sec = Math.floor(ms / 1000);
    return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
  }

  function activate(screenId) {
    document.querySelectorAll(".screen").forEach((node) => node.classList.toggle("active", node.id === screenId));
  }

  function updateHud() {
    $("roundMeter").textContent = `${Math.min(state.currentRound + 1, state.sessionRounds.length)}/${state.sessionRounds.length}`;
    $("timerMeter").textContent = state.startedAt ? formatTime(Date.now() - state.startedAt) : "0:00";
    $("scoreMeter").textContent = String(state.score);
    $("progressBar").style.width = `${(state.currentRound / state.sessionRounds.length) * 100}%`;
  }

  function startGame() {
    state.collectionMode = detectMode();
    state.variantId = "rank4";
    $("variantSelect").value = "rank4";
    state.sessionId = makeId("arena");
    state.participantCode = $("participantInput").value.trim() || makeId("guest").slice(0, 18);
    state.ageGroup = "not_collected";
    state.startedAt = Date.now();
    state.currentRound = 0;
    state.sessionRounds = chooseSessionRounds(`${state.sessionId}|${state.participantCode}|${state.variantId}`);
    state.score = 0;
    state.responses = [];
    state.events = [];
    state.playCounts = {};
    state.seed = makeId("seed");
    state.isFinishingRound = false;
    state.isFinished = false;
    logEvent("session_start", {
      variantId: state.variantId,
      collectionMode: state.collectionMode,
      roundPoolSize: allRounds.length,
      sessionRoundIds: state.sessionRounds.map((round) => round.id),
      priorityWeights: state.sessionRounds.map((round) => round.priorityWeight || 0),
      selectionPolicy: "weighted_without_replacement_by_session_seed",
      featureCoverageNote: "Rounds are sampled across the 13-round pool; low-redundancy rounds get modest extra weight but are not fixed every session."
    });
    activate("game");
    timerId = window.setInterval(updateHud, 500);
    renderRound();
    sendLog(false);
  }

  function renderRound() {
    const round = state.sessionRounds[state.currentRound];
    const variant = getVariant();
    state.roundStartedAt = Date.now();
    state.confidence = "not_asked";
    state.playCounts = {};
    $("roundTitle").textContent = `Round ${state.currentRound + 1}: ${variant.name}`;
    $("roundPrompt").textContent = variant.id === "rank4" ? "お手本に近いと思う順にA-Dを並べてください。" : (round.prompt || variant.short);
    $("nextBtn").disabled = true;
    document.querySelectorAll("[data-confidence]").forEach((button) => button.classList.remove("active"));

    const cards = shuffle(round.cards).map((card, index) => ({
      ...card,
      label: labels[index],
      instanceId: `${round.id}_${variant.id}_${index}_${card.feature}`,
      originalIndex: index
    }));
    state.trial = buildTrial(variant.id, round, cards);
    renderTrial();
    updateHud();
    logEvent("round_start", {
      roundId: round.id,
      variantId: variant.id,
      sharedSource: round.sharedSource || null,
      priorityWeight: round.priorityWeight || 0,
      roundMaxFeaturePairAbsCorr: round.roundMaxFeaturePairAbsCorr || 0,
      roundPairCorrPolicy: round.roundPairCorrPolicy || null,
      candidateFeatures: cards.map((card) => card.feature),
      candidateGroups: cards.map((card) => card.group)
    });
  }

  function buildTrial(variantId, round, cards) {
    const base = {
      variantId,
      roundId: round.id,
      prompt: round.prompt,
      sharedSource: round.sharedSource || null,
      priorityWeight: round.priorityWeight || 0,
      roundMaxFeaturePairAbsCorr: round.roundMaxFeaturePairAbsCorr || 0,
      roundPairCorrPolicy: round.roundPairCorrPolicy || null,
      cards,
      order: cards.slice(),
      selectedFeature: "",
      duelIndex: 0,
      duels: buildDuels(cards),
      duelResults: [],
      ratings: {},
      keepDrop: {}
    };
    cards.forEach((card) => {
      base.ratings[card.instanceId] = 0;
      base.keepDrop[card.instanceId] = "";
    });
    return base;
  }

  function buildDuels(cards) {
    const pairs = [[0, 1], [2, 3], [0, 2], [1, 3]];
    return pairs.map(([a, b]) => [cards[a], cards[b]]);
  }

  function renderTrial() {
    const variantId = state.trial.variantId;
    if (variantId === "rank4") renderRank4();
    if (variantId === "best_card") renderBestCard();
    if (variantId === "duel") renderDuel();
    if (variantId === "rating") renderRating();
    if (variantId === "keep_drop") renderKeepDrop();
    attachReferenceAudioLog();
  }

  function referenceHtml() {
    if (!state.trial.sharedSource) return "";
    const ref = state.trial.sharedSource;
    return `
      <section class="reference-clip">
        <div>
          <span class="badge">お手本</span>
          <strong>まずこれを聞く</strong>
        </div>
        <audio controls preload="metadata" src="${escapeHtml(clipSrc(ref.src))}" data-clip="reference"></audio>
      </section>
    `;
  }

  function renderRank4() {
    $("taskRoot").innerHTML = `${referenceHtml()}<p class="pair-label">お手本に近い順にA-Dを並べてください。カードはドラッグでも、上下ボタンでも動かせます。</p><div class="cards" id="cards"></div>`;
    const root = $("cards");
    state.trial.order.forEach((card, index) => {
      const node = cardNode(card, `${index + 1} 位`);
      node.draggable = true;
      node.dataset.instanceId = card.instanceId;
      attachRankDragHandlers(node, card);
      const row = document.createElement("div");
      row.className = "move-row";
      row.innerHTML = `<button type="button" class="ghost" data-move="-1" ${index === 0 ? "disabled" : ""}>上へ</button><button type="button" class="ghost" data-move="1" ${index === state.trial.order.length - 1 ? "disabled" : ""}>下へ</button>`;
      row.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", () => moveCard(index, index + Number(button.dataset.move)));
      });
      node.appendChild(row);
      root.appendChild(node);
    });
    updateNextEnabled();
  }

  function renderBestCard() {
    $("taskRoot").innerHTML = `${referenceHtml()}<p class="pair-label">お手本にいちばん近いものを1つ選んでください。</p><div class="cards" id="cards"></div>`;
    const root = $("cards");
    state.trial.cards.forEach((card) => {
      const node = cardNode(card, "候補");
      if (state.trial.selectedFeature === card.instanceId) node.classList.add("selected");
      const row = document.createElement("div");
      row.className = "choice-row";
      row.innerHTML = `<button type="button">これを選ぶ</button>`;
      row.querySelector("button").addEventListener("click", () => {
        state.trial.selectedFeature = card.instanceId;
        logEvent("best_card_select", { roundId: state.trial.roundId, feature: card.feature, group: card.group });
        renderBestCard();
        updateNextEnabled();
      });
      node.appendChild(row);
      root.appendChild(node);
    });
  }

  function renderDuel() {
    const duel = state.trial.duels[state.trial.duelIndex];
    $("taskRoot").innerHTML = `${referenceHtml()}<p class="pair-label">お手本に近い方を選んでください。${state.trial.duelIndex + 1}/${state.trial.duels.length}</p><div class="cards two" id="cards"></div>`;
    const root = $("cards");
    duel.forEach((card) => {
      const node = cardNode(card, "対決");
      const row = document.createElement("div");
      row.className = "choice-row";
      row.innerHTML = `<button type="button">こちらを選ぶ</button>`;
      row.querySelector("button").addEventListener("click", () => chooseDuel(card));
      node.appendChild(row);
      root.appendChild(node);
    });
    updateNextEnabled();
  }

  function chooseDuel(winner) {
    const [left, right] = state.trial.duels[state.trial.duelIndex];
    const loser = winner.instanceId === left.instanceId ? right : left;
    state.trial.duelResults.push({
      duelNumber: state.trial.duelIndex + 1,
      winner: cardMeta(winner),
      loser: cardMeta(loser),
      candidates: [cardMeta(left), cardMeta(right)]
    });
    logEvent("duel_select", { roundId: state.trial.roundId, winnerFeature: winner.feature, loserFeature: loser.feature });
    state.trial.duelIndex += 1;
    if (state.trial.duelIndex >= state.trial.duels.length) {
      $("nextBtn").disabled = false;
      renderDuelDone();
    } else {
      renderDuel();
    }
  }

  function renderDuelDone() {
    const wins = winCounts();
    $("taskRoot").innerHTML = `<div class="variant-summary"><b>記録しました</b><br>${state.trial.duelResults.length}回の二択を記録しました。迷い度を選んで決定してください。</div>`;
  }

  function renderRating() {
    $("taskRoot").innerHTML = `${referenceHtml()}<p class="pair-label">お手本に近いほど高い点をつけてください。</p><div class="cards" id="cards"></div>`;
    const root = $("cards");
    state.trial.cards.forEach((card) => {
      const node = cardNode(card, "点数");
      const row = document.createElement("div");
      row.className = "rating-row";
      [1, 2, 3, 4, 5].forEach((value) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "ghost";
        if (state.trial.ratings[card.instanceId] === value) button.classList.add("active");
        button.textContent = `${value}`;
        button.addEventListener("click", () => {
          state.trial.ratings[card.instanceId] = value;
          logEvent("rating_set", { roundId: state.trial.roundId, feature: card.feature, group: card.group, rating: value });
          renderRating();
          updateNextEnabled();
        });
        row.appendChild(button);
      });
      node.appendChild(row);
      root.appendChild(node);
    });
    updateNextEnabled();
  }

  function renderKeepDrop() {
    $("taskRoot").innerHTML = `${referenceHtml()}<p class="pair-label">お手本に近いと感じたものを残してください。</p><div class="cards" id="cards"></div>`;
    const root = $("cards");
    state.trial.cards.forEach((card) => {
      const node = cardNode(card, "仕分け");
      const row = document.createElement("div");
      row.className = "keep-row";
      ["keep", "drop"].forEach((value) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "ghost";
        if (state.trial.keepDrop[card.instanceId] === value) button.classList.add("active");
        button.textContent = value === "keep" ? "残す" : "外す";
        button.addEventListener("click", () => {
          state.trial.keepDrop[card.instanceId] = value;
          logEvent("keep_drop_set", { roundId: state.trial.roundId, feature: card.feature, group: card.group, decision: value });
          renderKeepDrop();
          updateNextEnabled();
        });
        row.appendChild(button);
      });
      node.appendChild(row);
      root.appendChild(node);
    });
    updateNextEnabled();
  }

  function cardNode(card, status) {
    const node = document.createElement("article");
    node.className = "card";
    if (state.trial.sharedSource) {
      node.innerHTML = `
        <div class="rank"><span class="badge">${escapeHtml(card.label)}</span><span>${escapeHtml(status)}</span></div>
        <strong>候補 ${escapeHtml(card.label)}</strong>
        <div class="audio-box single">
          <div>
            <div class="clip-label">候補 <span>短い音</span></div>
            <audio controls preload="metadata" src="${escapeHtml(clipSrc(card.target))}" data-card="${escapeHtml(card.instanceId)}" data-clip="target"></audio>
          </div>
        </div>
      `;
    } else {
      node.innerHTML = `
      <div class="rank"><span class="badge">${escapeHtml(card.label)}</span><span>${escapeHtml(status)}</span></div>
      <strong>Card ${escapeHtml(card.label)}</strong>
      <p class="pair-label">2つの音がどれくらい近いかを聞いてください。</p>
      <div class="audio-box">
        <div>
          <div class="clip-label">Clip 1 <span>短い音</span></div>
          <audio controls preload="metadata" src="${escapeHtml(clipSrc(card.source))}" data-card="${escapeHtml(card.instanceId)}" data-clip="source"></audio>
        </div>
        <div>
          <div class="clip-label">Clip 2 <span>短い音</span></div>
          <audio controls preload="metadata" src="${escapeHtml(clipSrc(card.target))}" data-card="${escapeHtml(card.instanceId)}" data-clip="target"></audio>
        </div>
      </div>
    `;
    }
    node.querySelectorAll("audio").forEach((audio) => attachAudioLog(audio, card));
    return node;
  }

  function attachReferenceAudioLog() {
    const audio = document.querySelector(".reference-clip audio");
    if (!audio || audio.dataset.bound === "1") return;
    audio.dataset.bound = "1";
    audio.addEventListener("play", () => {
      const key = `${state.trial.roundId}:reference`;
      state.playCounts[key] = (state.playCounts[key] || 0) + 1;
      logEvent("audio_play", {
        roundId: state.trial.roundId,
        variantId: state.trial.variantId,
        clip: "reference",
        playCount: state.playCounts[key],
        sharedSource: state.trial.sharedSource,
        src: audio.currentSrc || audio.getAttribute("src")
      });
    });
  }

  function attachAudioLog(audio, card) {
    audio.addEventListener("play", () => {
      const key = `${card.instanceId}:${audio.dataset.clip}`;
      state.playCounts[key] = (state.playCounts[key] || 0) + 1;
      logEvent("audio_play", {
        roundId: state.trial.roundId,
        variantId: state.trial.variantId,
        cardFeature: card.feature,
        cardGroup: card.group,
        cardInstanceId: card.instanceId,
        clip: audio.dataset.clip,
        playCount: state.playCounts[key],
        src: audio.currentSrc || audio.getAttribute("src")
      });
    });
    audio.addEventListener("ended", () => {
      logEvent("audio_ended", {
        roundId: state.trial.roundId,
        variantId: state.trial.variantId,
        cardFeature: card.feature,
        cardGroup: card.group,
        cardInstanceId: card.instanceId,
        clip: audio.dataset.clip
      });
    });
  }

  function moveCard(from, to) {
    if (to < 0 || to >= state.trial.order.length || from === to) return;
    const [card] = state.trial.order.splice(from, 1);
    state.trial.order.splice(to, 0, card);
    logEvent("rank_move", {
      roundId: state.trial.roundId,
      feature: card.feature,
      fromRank: from + 1,
      toRank: to + 1,
      order: state.trial.order.map((item) => item.feature)
    });
    renderRank4();
    updateNextEnabled();
  }

  function moveCardByInstance(draggedId, targetId) {
    if (!draggedId || !targetId || draggedId === targetId) return;
    const from = state.trial.order.findIndex((card) => card.instanceId === draggedId);
    const to = state.trial.order.findIndex((card) => card.instanceId === targetId);
    if (from < 0 || to < 0) return;
    const [card] = state.trial.order.splice(from, 1);
    state.trial.order.splice(to, 0, card);
    logEvent("rank_drag", {
      roundId: state.trial.roundId,
      feature: card.feature,
      fromRank: from + 1,
      toRank: to + 1,
      order: state.trial.order.map((item) => item.feature)
    });
    renderRank4();
    updateNextEnabled();
  }

  function attachRankDragHandlers(node, card) {
    node.addEventListener("dragstart", (event) => {
      node.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.instanceId);
      logEvent("rank_drag_start", {
        roundId: state.trial.roundId,
        feature: card.feature,
        rank: state.trial.order.findIndex((item) => item.instanceId === card.instanceId) + 1
      });
    });
    node.addEventListener("dragend", () => {
      document.querySelectorAll(".card.dragging, .card.drop-target").forEach((item) => {
        item.classList.remove("dragging", "drop-target");
      });
    });
    node.addEventListener("dragenter", (event) => {
      event.preventDefault();
      node.classList.add("drop-target");
    });
    node.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    });
    node.addEventListener("dragleave", () => {
      node.classList.remove("drop-target");
    });
    node.addEventListener("drop", (event) => {
      event.preventDefault();
      node.classList.remove("drop-target");
      moveCardByInstance(event.dataTransfer.getData("text/plain"), card.instanceId);
    });
    node.addEventListener("pointerdown", (event) => startTouchRankDrag(event, node, card));
    node.addEventListener("touchstart", (event) => startTouchRankDrag(event, node, card), { passive: true });
  }

  function startTouchRankDrag(event, node, card) {
    if (!document.body.classList.contains("mobile-layout")) return;
    if (event.pointerType === "mouse") return;
    if (event.target.closest("audio, button, input, select, a")) return;
    const point = event.touches?.[0] || event;
    clearTouchRankDrag();
    touchDrag = {
      node,
      card,
      pointerId: event.pointerId || 1,
      sourceType: event.type.startsWith("touch") ? "touch" : "pointer",
      active: false,
      lastTarget: null,
      startX: point.clientX,
      startY: point.clientY,
      timer: window.setTimeout(() => activateTouchRankDrag(event.pointerId || 1), 420)
    };
    document.addEventListener("pointermove", updateTouchRankDrag, { passive: false });
    document.addEventListener("pointerup", finishTouchRankDrag, { passive: false });
    document.addEventListener("pointercancel", cancelTouchRankDrag);
    document.addEventListener("touchmove", updateTouchRankDrag, { passive: false });
    document.addEventListener("touchend", finishTouchRankDrag, { passive: false });
    document.addEventListener("touchcancel", cancelTouchRankDrag);
  }

  function activateTouchRankDrag(pointerId) {
    if (!touchDrag || touchDrag.pointerId !== pointerId) return;
    touchDrag.active = true;
    touchDrag.node.classList.add("touch-dragging");
    try {
      touchDrag.node.setPointerCapture?.(pointerId);
    } catch {
      // Synthetic and some mobile events cannot be captured; document-level tracking continues.
    }
    logEvent("rank_touch_hold", {
      roundId: state.trial.roundId,
      feature: touchDrag.card.feature,
      rank: state.trial.order.findIndex((item) => item.instanceId === touchDrag.card.instanceId) + 1
    });
  }

  function updateTouchRankDrag(event) {
    if (!touchDrag) return;
    if (touchDrag.sourceType === "touch" && event.type.startsWith("pointer")) return;
    if (touchDrag.sourceType === "pointer" && event.type.startsWith("touch")) return;
    const point = event.touches?.[0] || event;
    if (!point || !Number.isFinite(point.clientX) || !Number.isFinite(point.clientY)) return;
    const moved = Math.hypot(point.clientX - touchDrag.startX, point.clientY - touchDrag.startY);
    if (!touchDrag.active && moved > 12) {
      clearTouchRankDrag();
      return;
    }
    if (!touchDrag.active) return;
    event.preventDefault();
    const target = cardAtPoint(point.clientX, point.clientY);
    document.querySelectorAll(".card.drop-target").forEach((item) => item.classList.remove("drop-target"));
    if (target && target !== touchDrag.node) {
      target.classList.add("drop-target");
      touchDrag.lastTarget = target;
    }
  }

  function finishTouchRankDrag(event) {
    if (!touchDrag) return;
    if (touchDrag.sourceType === "touch" && event.type.startsWith("pointer")) return;
    if (touchDrag.sourceType === "pointer" && event.type.startsWith("touch")) return;
    if (touchDrag.active) {
      event.preventDefault();
      const point = event.changedTouches?.[0] || event;
      const target = point ? cardAtPoint(point.clientX, point.clientY) || touchDrag.lastTarget : touchDrag.lastTarget;
      if (target && target !== touchDrag.node) moveCardByInstance(touchDrag.card.instanceId, target.dataset.instanceId);
    }
    clearTouchRankDrag();
  }

  function cancelTouchRankDrag() {
    clearTouchRankDrag();
  }

  function cardAtPoint(x, y) {
    const byRect = Array.from(document.querySelectorAll(".card")).find((card) => {
      const rect = card.getBoundingClientRect();
      return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
    });
    return byRect || document.elementFromPoint(x, y)?.closest(".card") || null;
  }

  function clearTouchRankDrag() {
    if (!touchDrag) return;
    window.clearTimeout(touchDrag.timer);
    touchDrag.node.classList.remove("touch-dragging");
    document.removeEventListener("pointermove", updateTouchRankDrag);
    document.removeEventListener("pointerup", finishTouchRankDrag);
    document.removeEventListener("pointercancel", cancelTouchRankDrag);
    document.removeEventListener("touchmove", updateTouchRankDrag);
    document.removeEventListener("touchend", finishTouchRankDrag);
    document.removeEventListener("touchcancel", cancelTouchRankDrag);
    document.querySelectorAll(".card.drop-target").forEach((item) => item.classList.remove("drop-target"));
    touchDrag = null;
  }

  function setConfidence(value) {
    state.confidence = value;
    document.querySelectorAll("[data-confidence]").forEach((button) => button.classList.toggle("active", button.dataset.confidence === value));
    logEvent("confidence_set", { roundId: state.trial?.roundId || "", confidence: value });
    updateNextEnabled();
  }

  function updateNextEnabled() {
    if (!state.trial) {
      $("nextBtn").disabled = true;
      return;
    }
    const variantId = state.trial.variantId;
    let ready = true;
    if (variantId === "best_card") ready = Boolean(state.trial.selectedFeature);
    if (variantId === "duel") ready = state.trial.duelIndex >= state.trial.duels.length;
    if (variantId === "rating") ready = Object.values(state.trial.ratings).every((value) => value > 0);
    if (variantId === "keep_drop") ready = Object.values(state.trial.keepDrop).every(Boolean);
    $("nextBtn").disabled = !ready;
  }

  async function finishRound() {
    if (state.isFinishingRound || state.isFinished) return;
    state.isFinishingRound = true;
    $("nextBtn").disabled = true;
    const elapsedMs = Date.now() - state.roundStartedAt;
    const response = buildResponse(elapsedMs);
    state.responses.push(response);
    state.score += scoreResponse(response);
    logEvent("round_finish", {
      roundId: state.trial.roundId,
      variantId: state.trial.variantId,
      elapsedMs,
      confidence: state.confidence,
      responseSummary: response.responseSummary
    });
    state.currentRound += 1;
    sendLog(false);
    if (state.currentRound >= state.sessionRounds.length) {
      await finishGame();
    } else {
      renderRound();
      state.isFinishingRound = false;
    }
  }

  function buildResponse(elapsedMs) {
    const trial = state.trial;
    const response = {
      responseId: makeId("resp"),
      variantId: trial.variantId,
      roundId: trial.roundId,
      prompt: trial.prompt,
      elapsedMs,
      confidence: state.confidence,
      sharedSource: trial.sharedSource,
      priorityWeight: trial.priorityWeight,
      roundMaxFeaturePairAbsCorr: trial.roundMaxFeaturePairAbsCorr,
      roundPairCorrPolicy: trial.roundPairCorrPolicy,
      candidateSet: trial.cards.map(cardMeta),
      playCounts: { ...state.playCounts },
      responseSummary: {},
      ranking: [],
      selected: null,
      duels: [],
      ratings: [],
      keepDrop: []
    };
    if (trial.variantId === "rank4") {
      response.ranking = trial.order.map((card, index) => ({ rank: index + 1, ...cardMeta(card) }));
      response.responseSummary = { type: "ranking", topFeature: response.ranking[0]?.feature || "" };
    }
    if (trial.variantId === "best_card") {
      const selected = trial.cards.find((card) => card.instanceId === trial.selectedFeature);
      response.selected = selected ? cardMeta(selected) : null;
      response.responseSummary = { type: "top1", selectedFeature: selected?.feature || "" };
    }
    if (trial.variantId === "duel") {
      response.duels = trial.duelResults;
      const wins = winCounts();
      response.ranking = trial.cards
        .map((card) => ({ rank: 0, wins: wins[card.feature] || 0, ...cardMeta(card) }))
        .sort((a, b) => b.wins - a.wins)
        .map((row, index) => ({ ...row, rank: index + 1 }));
      response.responseSummary = { type: "pairwise", topFeature: response.ranking[0]?.feature || "" };
    }
    if (trial.variantId === "rating") {
      response.ratings = trial.cards.map((card) => ({ rating: trial.ratings[card.instanceId], ...cardMeta(card) }));
      response.responseSummary = { type: "rating", maxRating: Math.max(...response.ratings.map((row) => row.rating)) };
    }
    if (trial.variantId === "keep_drop") {
      response.keepDrop = trial.cards.map((card) => ({ decision: trial.keepDrop[card.instanceId], ...cardMeta(card) }));
      response.responseSummary = { type: "keep_drop", keepCount: response.keepDrop.filter((row) => row.decision === "keep").length };
    }
    return response;
  }

  function winCounts() {
    const wins = {};
    state.trial.duelResults.forEach((result) => {
      wins[result.winner.feature] = (wins[result.winner.feature] || 0) + 1;
    });
    return wins;
  }

  function cardMeta(card) {
    return {
      instanceId: card.instanceId,
      label: card.label,
      feature: card.feature,
      group: card.group,
      piece: card.piece,
      segmentMode: card.mode,
      pair: card.pair,
      distance: Number(card.distance),
      source: card.source,
      target: card.target,
      sourceStartSec: card.sourceStartSec,
      sourceEndSec: card.sourceEndSec,
      targetStartSec: card.targetStartSec,
      targetEndSec: card.targetEndSec,
      sourceNodeId: card.sourceNodeId || "",
      targetNodeId: card.targetNodeId || "",
      targetFeature: card.targetFeature || card.feature,
      featureContributionRank: Number(card.featureContributionRank || 0),
      targetFeatureAbsZDiff: Number(card.targetFeatureAbsZDiff ?? card.distance),
      featureSelectionScore: Number(card.featureSelectionScore || 0),
      redundancyBucket: card.redundancyBucket || "",
      maxAbsCorrelation: Number(card.maxAbsCorrelation || 0),
      maxCorrelationPartner: card.maxCorrelationPartner || ""
    };
  }

  function clipSrc(src) {
    if (!src || !src.includes(".wav")) return src;
    return `${src}${src.includes("?") ? "&" : "?"}v=${CLIP_VERSION}`;
  }

  function scoreResponse(response) {
    const timeBonus = Math.max(20, 90 - Math.floor(response.elapsedMs / 2200));
    return timeBonus + 10;
  }

  function logEvent(type, payload = {}) {
    const event = {
      type,
      appVersion: APP_VERSION,
      collectionMode: state.collectionMode,
      sessionId: state.sessionId,
      participantCode: state.participantCode,
      at: new Date().toISOString(),
      elapsedMs: state.startedAt ? Date.now() - state.startedAt : 0,
      roundIndex: state.currentRound,
      ...payload
    };
    state.events.push(event);
    return event;
  }

  function buildPayload(final) {
    return {
      schema: "open_campus_feature_game.v2",
      appName: "Sound Match Arena",
      appVersion: APP_VERSION,
      collectionMode: state.collectionMode,
      final,
      sessionId: state.sessionId,
      participantCode: state.participantCode,
      ageGroup: state.ageGroup,
      variantId: state.variantId,
      variantName: getVariant().name,
      seed: state.seed,
      startedAt: new Date(state.startedAt).toISOString(),
      finishedAt: final ? new Date().toISOString() : null,
      totalElapsedMs: state.startedAt ? Date.now() - state.startedAt : 0,
      score: state.score,
      roundsPlanned: state.sessionRounds.length,
      roundPoolSize: allRounds.length,
      sessionRoundIds: state.sessionRounds.map((round) => round.id),
      roundsCompleted: state.responses.length,
      environment: {
        userAgent: navigator.userAgent,
        language: navigator.language,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        viewport: { width: window.innerWidth, height: window.innerHeight },
        devicePixelRatio: window.devicePixelRatio || 1,
        layout: document.body.classList.contains("mobile-layout") ? "mobile" : "desktop",
        url: window.location.href
      },
      responses: state.responses,
      events: state.events
    };
  }

  async function sendLog(final) {
    const body = buildPayload(final);
    localStorage.setItem(`sound_match_arena_${state.sessionId}`, JSON.stringify(body));
    localStorage.setItem("sound_match_arena_latest_session", state.sessionId);
    try {
      await fetch(new URL("api/log", window.location.href), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
    } catch (error) {
      logEvent("log_send_failed", { message: String(error) });
    }
    return body;
  }

  async function finishGame() {
    if (state.isFinished) return;
    state.isFinished = true;
    state.isFinishingRound = false;
    if (timerId) window.clearInterval(timerId);
    timerId = null;
    logEvent("session_finish", { totalElapsedMs: Date.now() - state.startedAt, score: state.score, completed: state.responses.length >= state.sessionRounds.length });
    activate("finish");
    const payload = buildPayload(true);
    sendLog(true);
    $("progressBar").style.width = "100%";
    const shortCode = state.sessionId.split("-").slice(-1)[0].toUpperCase();
    $("resultCode").textContent = shortCode;
    $("finishText").textContent = `${getVariant().name}を${formatTime(payload.totalElapsedMs)}で完了しました。`;
    $("summaryTable").innerHTML = `
      <tr><td>保存モード</td><td>${escapeHtml(state.collectionMode)}</td></tr>
      <tr><td>参加コード</td><td>${escapeHtml(state.participantCode)}</td></tr>
      <tr><td>ゲーム形式</td><td>${escapeHtml(getVariant().name)}</td></tr>
      <tr><td>回答ラウンド</td><td>${payload.roundsCompleted}/${payload.roundsPlanned}</td></tr>
      <tr><td>保存キー</td><td>${escapeHtml(state.sessionId)}</td></tr>
    `;
    updateHud();
  }

  function resetToIntro() {
    activate("intro");
    $("roundMeter").textContent = `0/${roundsPerSession}`;
    $("timerMeter").textContent = "0:00";
    $("scoreMeter").textContent = "0";
  }

  function buildCsv() {
    const rows = [[
      "session_id", "collection_mode", "variant_id", "age_group", "round_id", "elapsed_ms", "confidence", "metric", "value", "feature", "group", "piece", "segment_mode", "pair", "distance", "feature_rank", "redundancy_bucket", "max_abs_corr"
    ]];
    state.responses.forEach((response) => {
      response.ranking.forEach((item) => rows.push(csvRow(response, "rank", item.rank, item)));
      if (response.selected) rows.push(csvRow(response, "selected", 1, response.selected));
      response.ratings.forEach((item) => rows.push(csvRow(response, "rating", item.rating, item)));
      response.keepDrop.forEach((item) => rows.push(csvRow(response, "keep", item.decision === "keep" ? 1 : 0, item)));
      response.duels.forEach((duel) => {
        rows.push(csvRow(response, "duel_win", 1, duel.winner));
        rows.push(csvRow(response, "duel_loss", 0, duel.loser));
      });
    });
    return rows.map((row) => row.map((cell) => `"${String(cell ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  }

  function csvRow(response, metric, value, item) {
    return [
      state.sessionId, state.collectionMode, response.variantId, state.ageGroup, response.roundId,
      response.elapsedMs, response.confidence, metric, value, item.feature, item.group, item.piece,
      item.segmentMode, item.pair, item.distance, item.featureContributionRank, item.redundancyBucket,
      item.maxAbsCorrelation
    ];
  }

  function download(name, content, type) {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function showToast(text) {
    $("toast").textContent = text;
    $("toast").classList.add("show");
    window.setTimeout(() => $("toast").classList.remove("show"), 1600);
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  }

  window.addEventListener("error", (event) => {
    if (state.sessionId) logEvent("client_error", { message: event.message, filename: event.filename, lineno: event.lineno });
  });
  window.addEventListener("beforeunload", () => {
    if (state.sessionId && state.responses.length && state.responses.length < state.sessionRounds.length) {
      navigator.sendBeacon?.(new URL("api/log", window.location.href), JSON.stringify(buildPayload(false)));
    }
  });

  init();
})();
