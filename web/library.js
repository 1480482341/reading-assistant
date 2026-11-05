const STATUS_LABELS = { pending: "待分析", ready: "可读", read: "已读" };

const state = { tags: new Set(), status: "all" };
let articles = [];
let allTags = [];
let loadError = false;

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
  for (const tag of allTags) {
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

function emptyText() {
  if (loadError) return "文章库加载失败，请刷新重试。";
  if (articles.length === 0) return "文章库为空，等待后台抓取完成。";
  return "没有匹配的文章。";
}

function render() {
  syncFilters();
  const visible = articles.filter(matches);
  listEl.innerHTML = "";
  emptyEl.hidden = visible.length > 0;
  emptyEl.textContent = emptyText();

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

function getJson(url) {
  return fetch(url).then(resp => {
    if (!resp.ok) throw new Error(`${url} ${resp.status}`);
    return resp.json();
  });
}

async function load() {
  const [tagsResult, articlesResult] = await Promise.allSettled([
    getJson("/api/tags"),
    getJson("/api/articles/library"),
  ]);
  if (tagsResult.status === "fulfilled") {
    allTags = tagsResult.value.tags || [];
  }
  if (articlesResult.status === "fulfilled") {
    articles = articlesResult.value;
  } else {
    articles = [];
    loadError = true;
  }
  renderTagButtons();
  render();
}

load();
