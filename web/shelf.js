const STATUS_LABELS = { pending: "待分析", ready: "可读", read: "已读" };

let shelfItems = [];
let historyItems = [];
let shelfLoadError = false;
let historyLoadError = false;
let activeTab = "shelf";
// /api/history rows carry no annotation/bookmark counts, so resolve them
// from the library listing (all articles with counts) keyed by article id.
const countsById = new Map();

const shelfListEl = document.getElementById("shelf-list");
const historyListEl = document.getElementById("history-list");
const shelfEmptyEl = document.getElementById("shelf-empty");
const historyEmptyEl = document.getElementById("history-empty");
const tabEls = document.querySelectorAll(".tabs button");

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function titleHtml(item) {
  return escapeHtml(item.title_zh || item.title);
}

function metaHtml(item) {
  const parts = [item.source, STATUS_LABELS[item.status] || item.status];
  return parts.filter(Boolean).map(escapeHtml).join(" · ");
}

// "书签 N · 标色 M" for the item, or "" when the counts are unknown.
function marksHtml(item) {
  const row = (item.bookmark_count == null || item.annotation_count == null)
    ? countsById.get(item.id)
    : item;
  if (!row || row.bookmark_count == null || row.annotation_count == null) return "";
  return `书签 ${escapeHtml(row.bookmark_count)} · 标色 ${escapeHtml(row.annotation_count)}`;
}

function historyHtml(item) {
  const last = String(item.last_opened || "").slice(0, 10);
  const datePart = last ? ` · 最后 ${escapeHtml(last)}` : "";
  return `打开 ${escapeHtml(item.open_count)} 次${datePart}`;
}

function renderList(listEl, items, kind) {
  listEl.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    li.className = "item-card";
    li.dataset.id = item.id;
    const marks = marksHtml(item);
    const extra = kind === "shelf" ? "" : `<div class="history-line">${historyHtml(item)}</div>`;
    const btnLabel = kind === "shelf" ? "移出书架" : "加入书架";
    li.innerHTML = `
      <div class="item-title">${titleHtml(item)}</div>
      <div class="meta">${metaHtml(item)}</div>
      ${marks ? `<div class="marks">${marks}</div>` : ""}
      ${extra}
      <button class="card-btn">${btnLabel}</button>`;
    const btn = li.querySelector(".card-btn");
    btn.addEventListener("click", async event => {
      event.stopPropagation();
      await changeShelf(item, kind);
    });
    li.addEventListener("click", () => { window.location.href = `/?id=${item.id}`; });
    listEl.appendChild(li);
  }
}

async function changeShelf(item, kind) {
  const removing = kind === "shelf";
  try {
    const resp = await fetch(`/api/shelf/${item.id}`, {
      method: removing ? "DELETE" : "POST",
    });
    if (!resp.ok) return;
    // Reload both lists so the two tabs stay consistent after a mutation.
    await load();
  } catch (err) {
    console.error("Failed to update shelf:", err);
  }
}

function shelfEmptyText() {
  return shelfLoadError ? "书架加载失败，请刷新重试。" : "书架还是空的，去阅读页把文章加入书架吧。";
}

function historyEmptyText() {
  return historyLoadError ? "阅读历史加载失败，请刷新重试。" : "还没有阅读记录。";
}

function syncTabs() {
  for (const btn of tabEls) {
    btn.classList.toggle("active", btn.dataset.tab === activeTab);
  }
  shelfListEl.hidden = activeTab !== "shelf";
  historyListEl.hidden = activeTab !== "history";
  shelfEmptyEl.hidden = !(activeTab === "shelf" && shelfItems.length === 0);
  historyEmptyEl.hidden = !(activeTab === "history" && historyItems.length === 0);
}

function render() {
  shelfEmptyEl.textContent = shelfEmptyText();
  historyEmptyEl.textContent = historyEmptyText();
  renderList(shelfListEl, shelfItems, "shelf");
  renderList(historyListEl, historyItems, "history");
  syncTabs();
}

for (const btn of tabEls) {
  btn.addEventListener("click", () => {
    activeTab = btn.dataset.tab;
    syncTabs();
  });
}

function getJson(url) {
  return fetch(url).then(resp => {
    if (!resp.ok) throw new Error(`${url} ${resp.status}`);
    return resp.json();
  });
}

async function load() {
  const [shelfResult, historyResult, libraryResult] = await Promise.allSettled([
    getJson("/api/shelf"),
    getJson("/api/history"),
    getJson("/api/articles/library"),
  ]);
  if (shelfResult.status === "fulfilled") {
    shelfItems = shelfResult.value;
    shelfLoadError = false;
  } else {
    shelfItems = [];
    shelfLoadError = true;
  }
  if (historyResult.status === "fulfilled") {
    historyItems = historyResult.value;
    historyLoadError = false;
  } else {
    historyItems = [];
    historyLoadError = true;
  }
  countsById.clear();
  if (libraryResult.status === "fulfilled") {
    for (const row of libraryResult.value) countsById.set(row.id, row);
  }
  render();
}

load();
