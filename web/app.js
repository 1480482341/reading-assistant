let articleId = null;
let current = null;

const popup = document.getElementById("popup");
const bodyEl = document.getElementById("article-body");

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

async function loadArticle() {
  const today = await fetch("/api/articles/today").then(r => r.json());
  if (!today.length) {
    document.getElementById("article-title").textContent = "今天还没有文章";
    bodyEl.textContent = "点右上角可以粘贴链接或文本，或等后台抓取完成。";
    return;
  }
  articleId = today[0].id;
  const full = await fetch(`/api/articles/${articleId}`).then(r => r.json());
  document.getElementById("article-title").textContent = full.title;
  document.getElementById("article-meta").textContent =
    `${full.topic || ""} · ${full.word_count || ""} words · ${full.status}`;
  bodyEl.innerHTML = full.text
    .split(/\n+/).filter(Boolean)
    .map(p => `<p>${escapeHtml(p)}</p>`).join("");
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
  const text = String(sel).trim();
  if (!text || text.length > 500 || !articleId) return;
  const rect = sel.getRangeAt(0).getBoundingClientRect();

  const res = await fetch(
    `/api/lookup?article_id=${articleId}&text=${encodeURIComponent(text)}`
  ).then(r => r.json());

  if (res.hit) {
    showPopup(rect, res.item, text);
    return;
  }

  showPopup(rect, { term: text, gloss_zh: "分析中…" }, text);
  try {
    const miss = await fetch("/api/lookup/miss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ article_id: articleId, text }),
    }).then(r => r.json());
    showPopup(rect, miss.item, text);
  } catch (err) {
    showPopup(rect, { term: text, gloss_zh: "分析失败，已记录选区" }, text);
  }
}

function addToSidebar(item) {
  const list = item.type === "grammar"
    ? document.getElementById("grammar-list")
    : document.getElementById("marked-list");
  const li = document.createElement("li");
  li.innerHTML = `<span class="lemma">${escapeHtml(item.term)}</span>
                  <span class="count">${escapeHtml(item.gloss_zh || "")}</span>`;
  list.appendChild(li);
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
  popup.hidden = true;
}

document.addEventListener("mouseup", e => {
  if (popup.contains(e.target)) return;
  if (!bodyEl.contains(e.target)) { popup.hidden = true; return; }
  onSelect();
});
document.getElementById("popup-save").addEventListener("click", save);
document.getElementById("popup-close").addEventListener("click", () => { popup.hidden = true; });

loadArticle();
