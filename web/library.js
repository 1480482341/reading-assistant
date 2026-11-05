const TAGS = [
  "AI", "Computing", "Physics", "Math", "Biology", "Medicine", "Psychology",
  "Philosophy", "History", "Politics", "Economics", "Environment", "Art",
  "Literature", "Culture", "Society",
];

const STATUS_LABELS = { pending: "待分析", ready: "可读", read: "已读" };

const state = { tags: new Set(), status: "all" };
let articles = [];

const listEl = document.getElementById("article-list");
const tagFilterEl = document.getElementById("tag-filter");
const statusFilterEl = document.getElementById("status-filter");
const emptyEl = document.getElementById("empty-state");

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function renderTagButtons() {
  tagFilterEl.innerHTML = "";
  for (const tag of TAGS) {
    const btn = document.createElement("button");
    btn.textContent = tag;
    btn.dataset.tag = tag;
    btn.addEventListener("click", () => {
      if (state.tags.has(tag)) state.tags.delete(tag);
      else state.tags.add(tag);
      render();
    });
    tagFilterEl.appendChild(btn);
  }
}

function syncFilters() {
  for (const btn of statusFilterEl.querySelectorAll("button")) {
    btn.classList.toggle("active", btn.dataset.status === state.status);
  }
  for (const btn of tagFilterEl.querySelectorAll("button")) {
    btn.classList.toggle("active", state.tags.has(btn.dataset.tag));
  }
}

function matches(article) {
  if (state.status !== "all" && article.status !== state.status) return false;
  for (const tag of state.tags) {
    if (!article.tags.includes(tag)) return false;
  }
  return true;
}

function metaLine(article) {
  const parts = [
    article.source,
    article.published_at,
    article.word_count ? `${article.word_count} words` : "",
    STATUS_LABELS[article.status] || article.status,
  ].filter(Boolean);
  return parts.map(escapeHtml).join(" · ");
}

function render() {
  syncFilters();
  const visible = articles.filter(matches);
  listEl.innerHTML = "";
  emptyEl.hidden = articles.length === 0 || visible.length > 0;

  for (const article of visible) {
    const li = document.createElement("li");
    li.className = "article-card";
    li.dataset.id = article.id;
    const titleZh = article.title_zh
      ? `<div class="title-zh">${escapeHtml(article.title_zh)}</div>`
      : "";
    const tags = article.tags
      .map(tag => `<span class="tag">${escapeHtml(tag)}</span>`)
      .join("");
    li.innerHTML = `
      <div class="title-en">${escapeHtml(article.title)}</div>
      ${titleZh}
      <div class="meta">${metaLine(article)}</div>
      <div class="tags">${tags}</div>`;
    li.addEventListener("click", () => { window.location.href = `/?id=${article.id}`; });
    listEl.appendChild(li);
  }
}

statusFilterEl.addEventListener("click", e => {
  const btn = e.target.closest("button");
  if (!btn) return;
  state.status = btn.dataset.status;
  if (state.status === "all") state.tags.clear();
  render();
});

async function load() {
  try {
    articles = await fetch("/api/articles/library").then(r => r.json());
  } catch (err) {
    articles = [];
  }
  render();
}

renderTagButtons();
load();
