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
  const categoryEl = document.getElementById("card-category");
  categoryEl.textContent = item.category || "";
  categoryEl.hidden = !item.category;
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
  const rows = await fetch("/api/entries").then(r => r.json());
  const body = document.getElementById("list-body");
  const VOCABULARY_GROUP = "词汇与短语";
  const groupOf = row =>
    row.kind === "grammar" && row.category ? row.category : VOCABULARY_GROUP;
  const groupRank = row => (groupOf(row) === VOCABULARY_GROUP ? 0 : 1);
  const sorted = rows.slice().sort((a, b) => {
    const ra = groupRank(a);
    const rb = groupRank(b);
    if (ra !== rb) return ra - rb;
    const ga = groupOf(a);
    const gb = groupOf(b);
    if (ga !== gb) return ga.localeCompare(gb, "zh");
    return String(a.lemma).localeCompare(String(b.lemma), "zh");
  });
  const nodes = [];
  let group = null;
  for (const row of sorted) {
    const label = groupOf(row);
    if (label !== group) {
      group = label;
      const head = document.createElement("tr");
      head.className = "group-head";
      const td = document.createElement("td");
      td.colSpan = 3;
      td.textContent = label;
      head.appendChild(td);
      nodes.push(head);
    }
    const tr = document.createElement("tr");
    for (const value of [row.lemma, row.gloss || "", row.count]) {
      const td = document.createElement("td");
      td.textContent = String(value);
      tr.appendChild(td);
    }
    nodes.push(tr);
  }
  body.replaceChildren(...nodes);
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
