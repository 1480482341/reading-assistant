let articleId = null;
let current = null;
let popupToken = 0;
let full = null;
let annotations = [];
let bookmarks = [];

const popup = document.getElementById("popup");
const bodyEl = document.getElementById("article-body");

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

async function checkHealth() {
  try {
    const health = await fetch("/api/health").then(r => r.json());
    document.getElementById("banner").hidden = health.claude_available === true;
  } catch (err) {
    document.getElementById("banner").hidden = false;
  }
}

function hidePopup() {
  popupToken += 1;
  popup.hidden = true;
  const sel = window.getSelection();
  if (sel) sel.removeAllRanges();
}

function showMessage(title, body) {
  articleId = null;
  full = null;
  annotations = [];
  bookmarks = [];
  document.getElementById("article-title").textContent = title;
  document.getElementById("article-title-zh").hidden = true;
  document.getElementById("article-meta").textContent = "";
  bodyEl.textContent = body;
}

// Split article text exactly like the server's app/annotations.py:
// split_paragraphs — split on newline runs, trim each piece, drop empties.
function paragraphs() {
  return full.text.split(/\n+/).map(s => s.trim()).filter(Boolean);
}

// Rebuild the article body from paragraphs() and the current annotations,
// wrapping each highlighted range in a colored span with its annotation id.
function renderBody() {
  const paras = paragraphs();
  bodyEl.innerHTML = paras.map((para, i) => {
    const anns = annotations
      .filter(a => a.para_index === i)
      .sort((x, y) => x.start_offset - y.start_offset);
    const frags = [];
    let cursor = 0;
    for (const a of anns) {
      const start = Math.max(a.start_offset, cursor);
      const end = Math.min(a.end_offset, para.length);
      if (end <= start) continue;
      if (start > cursor) frags.push({ text: para.slice(cursor, start) });
      frags.push({ text: para.slice(start, end), ann: a });
      cursor = end;
    }
    if (cursor < para.length) frags.push({ text: para.slice(cursor) });
    const inner = frags.map(f => f.ann
      ? `<span class="hl hl-${f.ann.color}" data-annotation-id="${f.ann.id}">${escapeHtml(f.text)}</span>`
      : escapeHtml(f.text)).join("");
    return `<p data-para="${i}">${inner}</p>`;
  }).join("");
}

function showArticle(article) {
  full = article;
  articleId = full.id;
  document.getElementById("article-title").textContent = full.title;
  const titleZh = document.getElementById("article-title-zh");
  titleZh.textContent = full.title_zh || "";
  titleZh.hidden = !full.title_zh;
  document.getElementById("article-meta").textContent =
    `${full.topic || ""} · ${full.word_count || ""} words · ${full.status}`;
  annotations = full.annotations || [];
  bookmarks = full.bookmarks || [];
  renderBody();
  fetch(`/api/articles/${full.id}/marks`)
    .then(r => r.json())
    .then(renderRightPanel)
    .catch(err => console.error("Failed to load marks:", err));
}

async function loadArticle() {
  const requested = new URLSearchParams(location.search).get("id");
  if (requested && !/^\d+$/.test(requested)) {
    showMessage("文章不存在", "链接里的文章编号无效，回到文章库重新选择。");
    return;
  }
  if (requested) {
    const resp = await fetch(`/api/articles/${encodeURIComponent(requested)}`);
    if (!resp.ok) {
      showMessage("文章不存在", "这篇文章可能已被删除，回到文章库重新选择。");
      return;
    }
    showArticle(await resp.json());
    return;
  }
  const today = await fetch("/api/articles/today").then(r => r.json());
  if (!today.length) {
    showMessage("今天还没有文章",
      "还没有可读文章：等后台抓取完成，或用 POST /api/articles/ingest 粘贴链接或正文。");
    return;
  }
  const full = await fetch(`/api/articles/${today[0].id}`).then(r => r.json());
  showArticle(full);
}

function sentenceAround(text, needle) {
  const i = text.indexOf(needle);
  if (i < 0) return "";
  const start = text.lastIndexOf(".", i) + 1;
  let end = text.indexOf(".", i);
  end = end < 0 ? text.length : end + 1;
  return text.slice(start, end).trim();
}

function showPopup(rect, item, text) {
  current = { item, text };
  document.getElementById("popup-term").textContent = item.term || text;
  document.getElementById("popup-gloss").textContent = item.gloss_zh || "";
  document.getElementById("popup-why").textContent =
    [item.grammar_role, item.why].filter(Boolean).join(" · ");
  popup.hidden = false;
  const left = Math.min(window.scrollX + rect.left, window.scrollX + window.innerWidth - 300);
  popup.style.left = `${left}px`;
  popup.style.top = `${window.scrollY + rect.bottom + 8}px`;
}

async function onSelect() {
  const sel = window.getSelection();
  const text = String(sel).trim().slice(0, 500);
  if (!text || !articleId) return;
  const rect = sel.getRangeAt(0).getBoundingClientRect();
  const token = ++popupToken;

  const res = await fetch(
    `/api/lookup?article_id=${articleId}&text=${encodeURIComponent(text)}`
  ).then(r => r.json());
  if (token !== popupToken) return;

  if (res.hit) {
    showPopup(rect, res.item, text);
    return;
  }

  showPopup(rect, { term: text, gloss_zh: "分析中…（约 5–10 秒）" }, text);
  try {
    const resp = await fetch("/api/lookup/miss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ article_id: articleId, text }),
    });
    if (!resp.ok) throw new Error("model unavailable");
    const miss = await resp.json();
    if (token !== popupToken) return;
    showPopup(rect, miss.item, text);
  } catch (err) {
    if (token !== popupToken) return;
    showPopup(rect, { term: text, gloss_zh: "模型不可用，可先记下来" }, text);
  }
}

function appendMark(listEl, item) {
  const li = document.createElement("li");
  li.innerHTML = `<span class="lemma">${escapeHtml(item.term)}</span>
                  <span class="count">${escapeHtml(item.gloss_zh || "")}</span>`;
  listEl.appendChild(li);
}

// Fill both sidebar lists from GET /api/articles/{id}/marks.
function renderRightPanel(marks) {
  const markedList = document.getElementById("marked-list");
  const grammarList = document.getElementById("grammar-list");
  markedList.innerHTML = "";
  grammarList.innerHTML = "";
  for (const item of marks.occurrences || []) appendMark(markedList, item);
  for (const item of marks.grammar || []) appendMark(grammarList, item);
}

function addToSidebar(item) {
  const list = item.type === "grammar"
    ? document.getElementById("grammar-list")
    : document.getElementById("marked-list");
  appendMark(list, item);
}

async function save() {
  if (!current || !articleId) return;
  await fetch("/api/occurrences", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      article_id: articleId,
      text: current.text,
      sentence: current.item.sentence || sentenceAround(bodyEl.textContent, current.text),
      item: current.item,
    }),
  });
  addToSidebar(current.item);
  hidePopup();
}

document.addEventListener("mouseup", e => {
  if (popup.contains(e.target)) return;
  if (!bodyEl.contains(e.target)) { hidePopup(); return; }
  onSelect();
});
document.getElementById("popup-save").addEventListener("click", save);
document.getElementById("popup-close").addEventListener("click", hidePopup);
document.getElementById("mark-read").addEventListener("click", async e => {
  e.preventDefault();
  if (!articleId) return;
  await fetch(`/api/articles/${articleId}/read`, { method: "POST" });
  window.location.href = "/";
});

loadArticle();
checkHealth();
