let queue = [];
let index = 0;

const cardEl = document.getElementById("review-card");
const emptyEl = document.getElementById("empty-state");

function render() {
  document.getElementById("progress-text").textContent =
    queue.length ? `${index + 1} / ${queue.length}` : "— / —";
  if (!queue.length || index >= queue.length) {
    cardEl.hidden = true;
    emptyEl.hidden = false;
    emptyEl.textContent = queue.length ? "这一轮复习完了。" : "今天没有要复习的。";
    return;
  }
  const item = queue[index];
  cardEl.hidden = false;
  emptyEl.hidden = true;
  document.getElementById("card-word").textContent = item.lemma;
  document.getElementById("card-gloss").textContent = item.gloss || "";
  document.getElementById("card-sentence").textContent = item.sentence || "";
}

async function answer(known) {
  const item = queue[index];
  if (!item) return;
  await fetch(`/api/review/${item.entry_id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ known }),
  });
  index += 1;
  render();
}

async function load() {
  queue = await fetch("/api/review/queue").then(r => r.json());
  index = 0;
  render();
  const rows = await fetch("/api/export?format=csv").then(r => r.text());
  const body = document.getElementById("list-body");
  body.innerHTML = rows.trim().split("\n").slice(1).filter(Boolean).map(line => {
    const [kind, lemma, count, gloss] = line.split(",");
    return `<tr><td>${lemma}</td><td>${gloss || ""}</td><td>${count}</td></tr>`;
  }).join("");
}

document.getElementById("btn-known").addEventListener("click", () => answer(true));
document.getElementById("btn-unknown").addEventListener("click", () => answer(false));
document.getElementById("toggle-list").addEventListener("click", () => {
  const list = document.getElementById("list-view");
  const card = document.getElementById("card-view");
  list.hidden = !list.hidden;
  card.hidden = !list.hidden;
  document.getElementById("toggle-list").textContent = list.hidden ? "看列表" : "看卡片";
});

load();
