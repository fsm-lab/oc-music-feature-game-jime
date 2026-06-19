(() => {
  "use strict";

  const data = window.MUSIC_MATCH_DATA || { rounds: [] };
  const rounds = data.rounds || [];
  const labels = ["A", "B", "C", "D"];
  const clipVersion = "loudnorm-20260614-01";
  let roundIndex = 0;
  let score = 0;
  let order = [];

  const $ = (id) => document.getElementById(id);

  function show(id) {
    ["intro", "game", "finish"].forEach((name) => $(name).classList.toggle("hidden", name !== id));
  }

  function clip(src) {
    return `${src}${src.includes("?") ? "&" : "?"}v=${clipVersion}`;
  }

  function shuffle(items) {
    const copy = items.slice();
    for (let i = copy.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
  }

  function start() {
    roundIndex = 0;
    score = 0;
    show("game");
    renderRound();
  }

  function renderRound() {
    const round = rounds[roundIndex % rounds.length];
    $("roundLabel").textContent = `RACE ${roundIndex + 1}`;
    $("scoreText").textContent = String(score);
    $("referenceAudio").src = clip(round.sharedSource.src);
    order = shuffle(round.cards).map((card, index) => ({ ...card, label: labels[index] }));
    renderTrack();
  }

  function renderTrack() {
    const root = $("track");
    root.innerHTML = "";
    order.forEach((card, index) => {
      const row = document.createElement("article");
      row.className = "runner";
      row.innerHTML = `
        <span class="place">${index + 1}</span>
        <div>
          <strong>${card.label} レーン</strong>
          <audio controls preload="metadata" src="${clip(card.target)}"></audio>
        </div>
        <div class="runner-controls">
          <button type="button" class="ghost" data-dir="-1" ${index === 0 ? "disabled" : ""}>上へ</button>
          <button type="button" class="ghost" data-dir="1" ${index === order.length - 1 ? "disabled" : ""}>下へ</button>
        </div>
      `;
      row.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", () => move(index, index + Number(button.dataset.dir)));
      });
      root.appendChild(row);
    });
  }

  function move(from, to) {
    if (to < 0 || to >= order.length || from === to) return;
    const [item] = order.splice(from, 1);
    order.splice(to, 0, item);
    renderTrack();
  }

  function finishRace() {
    const best = order[0];
    const roundScore = Math.max(20, 100 - Math.round(Number(best.distance || 0) * 1000));
    score += roundScore;
    roundIndex += 1;
    if (roundIndex >= 3) {
      $("finishTitle").textContent = `${score} PTS`;
      $("finishText").textContent = "試作版なので本番ログには保存していません。順位予想の演出だけを確認するためのページです。";
      show("finish");
    } else {
      renderRound();
    }
  }

  $("startBtn").addEventListener("click", start);
  $("raceBtn").addEventListener("click", finishRace);
  $("shuffleBtn").addEventListener("click", renderRound);
  $("againBtn").addEventListener("click", start);
})();
