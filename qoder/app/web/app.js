/* StudyCoach front-end: no build step, no external assets.
   All numbers shown come from /api responses; nothing is mocked. */

const state = {
  mode: "hybrid",
  subjects: [],
  documents: [],
  traces: 0,
  lastQuery: "",
  busy: false,
};

const sessionId = (() => {
  let id = sessionStorage.getItem("studycoach_session");
  if (!id) {
    const rand = (crypto.randomUUID && crypto.randomUUID().slice(0, 8)) ||
      Math.random().toString(16).slice(2, 10);
    id = `web-${rand}`;
    sessionStorage.setItem("studycoach_session", id);
  }
  return id;
})();

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlight(text, keywords) {
  const terms = (keywords || []).filter((term) => term && term.length >= 2);
  if (!terms.length) return escapeHtml(text);
  const pattern = terms
    .slice()
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp)
    .join("|");
  const splitter = new RegExp(`(${pattern})`, "gi");
  return String(text)
    .split(splitter)
    .map((part, index) => (index % 2 === 1 ? `<mark>${escapeHtml(part)}</mark>` : escapeHtml(part)))
    .join("");
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" ? payload.detail || JSON.stringify(payload) : payload;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload;
}

let toastTimer = null;
function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("is-visible"), 3200);
}

function showPage(name) {
  $$(".page").forEach((panel) => panel.classList.toggle("is-active", panel.dataset.pagePanel === name));
  $$(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.page === name));
  if (name === "library") loadDocuments();
  if (name === "review") loadReview();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setStatus(kind, text) {
  const pill = $("#status-pill");
  pill.classList.remove("is-ok", "is-bad");
  if (kind) pill.classList.add(kind);
  $("#status-text").textContent = text;
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value.endsWith("Z") || value.includes("+") ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

/* ---------------- health + stats ---------------- */

async function loadHealth() {
  try {
    const data = await api("/health");
    const seekdb = data.integrations.seekdb;
    if (seekdb.status === "ok") {
      setStatus("is-ok", `seekdb · ${seekdb.chunks} chunks`);
    } else {
      setStatus("is-bad", "seekdb 异常");
    }
    $("#footer-stage").textContent = `stage ${data.stage} · v${data.version}`;
  } catch (error) {
    setStatus("is-bad", "后端不可达");
    $("#footer-stage").textContent = "后端不可达";
  }
}

async function loadDocuments() {
  try {
    const data = await api("/api/documents");
    state.documents = data.documents || [];
    renderLibrary(data.stats || {});
    renderAskStats(data.stats || {});
    renderSubjects(data.stats?.subjects || []);
    renderDocuments(state.documents);
  } catch (error) {
    toast(`资料库加载失败：${error.message}`);
  }
}

function renderAskStats(stats) {
  $("#ask-stats").innerHTML = `
    <div><strong>${stats.documents ?? 0}</strong>文档</div>
    <div><strong>${stats.chunks ?? 0}</strong>chunks</div>
  `;
}

function renderSubjects(subjects) {
  const select = $("#subject-filter");
  const current = select.value;
  select.innerHTML = `<option value="">全部学科</option>` +
    subjects.map((subject) => `<option value="${escapeHtml(subject)}">${escapeHtml(subject)}</option>`).join("");
  if (subjects.includes(current)) select.value = current;
}

function renderLibrary(stats) {
  const embedding = stats.embedding || {};
  $("#library-stats").innerHTML = `
    <div class="stat-card"><div class="stat-value">${stats.documents ?? 0}</div><div class="stat-label">文档</div></div>
    <div class="stat-card"><div class="stat-value">${stats.chunks ?? 0}</div><div class="stat-label">已索引 chunk</div></div>
    <div class="stat-card"><div class="stat-value">${(stats.subjects || []).length}</div><div class="stat-label">学科</div></div>
    <div class="stat-card"><div class="stat-value">${embedding.dimension ?? "—"}</div><div class="stat-label">向量维度 · ${escapeHtml(embedding.model || "未配置")}</div></div>
  `;
}

function renderDocuments(documents) {
  const list = $("#doc-list");
  const empty = $("#library-empty");
  empty.hidden = documents.length > 0;
  if (!documents.length) {
    list.innerHTML = "";
    return;
  }
  list.innerHTML = documents.map((doc) => `
    <article class="doc-row">
      <div class="doc-main">
        <p class="doc-title">${escapeHtml(doc.title)}</p>
        <div class="doc-meta">
          <span class="subject-tag">${escapeHtml(doc.subject)}</span>
          <span>${escapeHtml(doc.file_type.toUpperCase())}</span>
          <span>${doc.chunk_count} chunks</span>
          <span>导入于 ${formatDate(doc.imported_at)}</span>
          <span class="doc-path">${escapeHtml(doc.source_path)}</span>
        </div>
      </div>
      <button class="delete-btn" data-delete="${escapeHtml(doc.doc_id)}" title="删除该文档及其 chunk">删除</button>
    </article>
  `).join("");

  $$("[data-delete]", list).forEach((button) => {
    button.addEventListener("click", () => deleteDocument(button.dataset.delete));
  });
}

async function deleteDocument(docId) {
  const doc = state.documents.find((item) => item.doc_id === docId);
  if (!doc) return;
  if (!confirm(`删除「${doc.title}」及其 ${doc.chunk_count} 个 chunk？此操作不可撤销。`)) return;
  try {
    await api(`/api/documents/${encodeURIComponent(docId)}`, { method: "DELETE" });
    toast("已删除");
    await loadDocuments();
    await loadTraces();
  } catch (error) {
    toast(`删除失败：${error.message}`);
  }
}

/* ---------------- search ---------------- */

function setMode(mode) {
  state.mode = mode;
  $$(".seg").forEach((button) => button.classList.toggle("is-active", button.dataset.mode === mode));
}

async function runSearch(queryOverride) {
  const input = $("#query-input");
  const query = (queryOverride ?? input.value).trim();
  if (!query) {
    input.focus();
    return;
  }
  if (state.busy) return;
  input.value = query;
  state.busy = true;
  state.lastQuery = query;
  $("#search-btn").disabled = true;
  $("#search-btn").textContent = "检索中…";
  $("#ask-empty").hidden = true;

  const started = performance.now();
  try {
    const data = await api("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        mode: state.mode,
        subject: $("#subject-filter").value || null,
        top_k: 8,
        session_id: sessionId,
      }),
    });
    const elapsed = Math.round(performance.now() - started);
    renderSearch(data, elapsed);
    await loadTraces();
  } catch (error) {
    $("#search-meta").hidden = false;
    $("#search-meta").innerHTML = `<span>检索失败</span><span class="meta-note">${escapeHtml(error.message)}</span>`;
    $("#results").innerHTML = "";
    $("#answer-panel").hidden = true;
    toast(`检索失败：${error.message}`);
  } finally {
    state.busy = false;
    $("#search-btn").disabled = false;
    $("#search-btn").textContent = "检索证据";
  }
}

function renderSearch(data, elapsed) {
  const meta = $("#search-meta");
  meta.hidden = false;
  const modeLabel = { hybrid: "混合检索", vector: "仅向量", fulltext: "仅全文" }[data.mode] || data.mode;
  const filters = Object.entries(data.filters || {}).map(([key, value]) => `${key}=${value}`).join("，") || "无";
  meta.innerHTML = `
    <span><strong>${escapeHtml(modeLabel)}</strong></span>
    <span>关键词：${escapeHtml((data.keywords || []).join("、") || "无")}</span>
    <span>过滤：${escapeHtml(filters)}</span>
    <span class="mono">${elapsed} ms · ${escapeHtml(data.trace_id)}</span>
    <span class="meta-note">${escapeHtml(data.note || "")}${(data.notes || []).length ? " " + escapeHtml(data.notes.join("；")) : ""}</span>
  `;

  renderAnswer(data);
  renderResults(data);
}

function renderAnswer(data) {
  const panel = $("#answer-panel");
  if (!data.results.length) {
    panel.hidden = true;
    return;
  }
  const top = data.results.slice(0, 3);
  panel.hidden = false;
  panel.innerHTML = `
    <h2>证据摘要 · 由检索结果拼装</h2>
    <p>与「${escapeHtml(data.query)}」最相关的 ${top.length} 条原文如下。当前未配置 LLM，这里只摘录证据，不生成原文之外的推断。</p>
    <ol class="answer-list">
      ${top.map((hit) => `
        <li>
          <a href="#result-${escapeHtml(hit.chunk_id)}">${escapeHtml(hit.doc_title)} · ${escapeHtml(hit.section)}${hit.page ? ` · 第 ${hit.page} 页` : ""}</a>
          <div>${escapeHtml(hit.text.replace(/\s+/g, " ").slice(0, 110))}${hit.text.length > 110 ? "…" : ""}</div>
        </li>
      `).join("")}
    </ol>
    <p class="answer-note">S3 会在此处注入 PowerContext 中关于你的偏好与薄弱点，并把本轮结论写回记忆。</p>
  `;
}

function renderResults(data) {
  const container = $("#results");
  if (!data.results.length) {
    container.innerHTML = "";
    const empty = $("#ask-empty");
    empty.hidden = false;
    empty.querySelector(".empty-title").textContent = "没有命中";
    empty.querySelector("p:not(.empty-title)").textContent =
      "试试换个说法、取消学科过滤，或先在资料库导入文档。全文模式对词面更敏感，混合模式召回更宽。";
    return;
  }

  container.innerHTML = data.results.map((hit, index) => {
    const citation = `${hit.doc_title} · ${hit.section} · chunk ${hit.chunk_id}${hit.page ? ` · 第 ${hit.page} 页` : ""}`;
    return `
      <article class="result-card" id="result-${escapeHtml(hit.chunk_id)}">
        <div class="result-rank">${index + 1}</div>
        <div>
          <div class="result-head">
            <h3 class="result-title">${escapeHtml(hit.doc_title)}</h3>
            <span class="result-cite">
              ${escapeHtml(hit.section)}
              ${hit.page ? `<span class="sep">·</span>第 ${hit.page} 页` : ""}
              <span class="sep">·</span>${escapeHtml(hit.subject)}
            </span>
            <span class="badges">
              ${(hit.matched_by || []).map((tag) => `<span class="badge ${tag}">${tag === "vector" ? "向量" : "全文"}</span>`).join("")}
            </span>
          </div>
          <div class="score-line">
            <div class="score-bar"><div class="score-fill" style="width:${Math.max(2, Math.round((hit.relevance || 0) * 100))}%"></div></div>
            <span class="score-value">相关度 ${((hit.relevance || 0) * 100).toFixed(0)}%</span>
          </div>
          <p class="result-text">${highlight(hit.text, data.keywords)}</p>
          <div class="citation-row">
            <span class="mono">doc_id ${escapeHtml(hit.doc_id)}</span>
            <span class="mono">chunk ${escapeHtml(hit.chunk_id)}</span>
            <span>${hit.page ? `第 ${hit.page} 页` : "无页码"}</span>
            <button class="copy-btn" data-copy="${escapeHtml(citation)}">复制引用</button>
          </div>
        </div>
      </article>
    `;
  }).join("");

  $$("[data-copy]", container).forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copy);
        button.textContent = "已复制";
        setTimeout(() => (button.textContent = "复制引用"), 1400);
      } catch {
        toast("浏览器拒绝访问剪贴板");
      }
    });
  });
}

/* ---------------- traces ---------------- */

function setDrawer(open) {
  $("#trace-drawer").classList.toggle("is-open", open);
  $("#trace-drawer").setAttribute("aria-hidden", String(!open));
  $("#trace-toggle").setAttribute("aria-expanded", String(open));
  $("#drawer-backdrop").hidden = !open;
  if (open) loadTraces();
}

async function loadTraces() {
  try {
    const data = await api(`/api/traces?session_id=${encodeURIComponent(sessionId)}&limit=80`);
    const traces = data.traces || [];
    state.traces = traces.length;
    $("#trace-count").textContent = traces.length;
    const list = $("#trace-list");
    if (!traces.length) {
      list.innerHTML = `<div class="trace-empty">本会话还没有轨迹。执行一次检索或导入，就能在这里看到 seekdb 的真实调用。</div>`;
      return;
    }
    list.innerHTML = traces.map((trace) => `
      <details class="trace-item">
        <summary class="trace-item-head">
          <span class="trace-layer ${escapeHtml(trace.layer)}">${escapeHtml(trace.layer)}</span>
          <span class="trace-op">${escapeHtml(trace.operation)}</span>
          <span class="trace-time">${formatDate(trace.ts)}</span>
        </summary>
        <div class="trace-body">
          <p class="trace-summary">${escapeHtml(trace.summary)}</p>
          <p class="trace-input">输入：${escapeHtml(trace.input || "—")}</p>
          <p class="trace-input">返回：${trace.result_count} 条 · ${escapeHtml(trace.trace_id)}</p>
          <details class="trace-payload">
            <summary>查看 payload</summary>
            <pre>${escapeHtml(JSON.stringify(trace.payload, null, 2))}</pre>
          </details>
        </div>
      </details>
    `).join("");
  } catch (error) {
    $("#trace-list").innerHTML = `<div class="trace-empty">轨迹加载失败：${escapeHtml(error.message)}</div>`;
  }
}

/* ---------------- review (filled in S4) ---------------- */

async function loadReview() {
  // S4 replaces this with /api/review/today. Keep the hook so the page is live.
  const empty = $("#review-empty");
  if (!empty) return;
}

/* ---------------- demo mode ---------------- */

async function runDemo() {
  const button = $("#demo-btn");
  button.disabled = true;
  button.textContent = "演示中…";
  try {
    const seeded = await api("/api/ingest/seed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    const imported = (seeded.results || []).filter((item) => !item.skipped).length;
    toast(imported ? `已导入 ${imported} 份示例资料` : "示例资料已存在，直接开始检索");
    await loadDocuments();

    const questions = [
      "怎么防止模型过拟合？",
      "PCA 为什么要先中心化？",
      "我上次在正则化上错在哪？",
    ];
    for (const question of questions) {
      setMode("hybrid");
      $("#subject-filter").value = "";
      await runSearch(question);
      await new Promise((resolve) => setTimeout(resolve, 260));
    }
    setDrawer(true);
    toast("演示完成：三次检索都已写入技术轨迹");
    showPage("ask");
  } catch (error) {
    toast(`演示失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "演示模式";
  }
}

/* ---------------- wiring ---------------- */

function bindEvents() {
  $$("[data-page]").forEach((element) => {
    element.addEventListener("click", (event) => {
      event.preventDefault();
      showPage(element.dataset.page);
    });
  });

  $$(".seg").forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.mode));
  });

  $$("#example-chips .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      $("#query-input").value = chip.dataset.q;
      runSearch();
    });
  });

  $("#search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runSearch();
  });

  $("#query-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      runSearch();
    }
  });

  $("#trace-toggle").addEventListener("click", () => setDrawer(!$("#trace-drawer").classList.contains("is-open")));
  $("#trace-close").addEventListener("click", () => setDrawer(false));
  $("#drawer-backdrop").addEventListener("click", () => setDrawer(false));
  $("#trace-refresh").addEventListener("click", loadTraces);

  $("#demo-btn").addEventListener("click", runDemo);

  $("#seed-btn").addEventListener("click", async () => {
    const button = $("#seed-btn");
    button.disabled = true;
    try {
      const data = await api("/api/ingest/seed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const skipped = (data.results || []).filter((item) => item.skipped).length;
      toast(`导入完成：${data.results.length - skipped} 份新增，${skipped} 份已存在`);
      await loadDocuments();
      await loadTraces();
    } catch (error) {
      toast(`导入失败：${error.message}`);
    } finally {
      button.disabled = false;
    }
  });

  $("#upload-input").addEventListener("change", (event) => {
    const file = event.target.files[0];
    $("#upload-name").textContent = file ? file.name : "选择 md / txt / pdf";
  });

  $("#upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = $("#upload-input").files[0];
    if (!file) {
      toast("先选择一个 md / txt / pdf 文件");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("subject", $("#upload-subject").value);
    form.append("session_id", sessionId);
    const button = $("#upload-btn");
    button.disabled = true;
    button.textContent = "索引中…";
    try {
      const data = await api("/api/ingest/upload", { method: "POST", body: form });
      toast(`已索引「${data.result.title}」：${data.result.chunks} 个 chunk`);
      $("#upload-form").reset();
      $("#upload-name").textContent = "选择 md / txt / pdf";
      await loadDocuments();
      await loadTraces();
    } catch (error) {
      toast(`上传失败：${error.message}`);
    } finally {
      button.disabled = false;
      button.textContent = "上传并索引";
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && $("#trace-drawer").classList.contains("is-open")) setDrawer(false);
  });
}

async function boot() {
  bindEvents();
  await loadHealth();
  await loadDocuments();
  await loadTraces();
}

boot();
