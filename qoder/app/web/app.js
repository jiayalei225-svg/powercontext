/* StudyCoach front-end: no build step, no external assets.
   Every number and every memory shown comes from an API response. */

const state = {
  mode: "hybrid",
  sessionId: "",
  documents: [],
  memories: [],
  traces: 0,
  lastQuestion: "",
  lastAsk: null,
  review: null,
  quiz: null,
  quizSession: "",
  busy: false,
};

state.sessionId = (() => {
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

const KIND_LABELS = {
  profile: "学习偏好",
  weakness: "薄弱点与错因",
  session_summary: "会话摘要",
  plan: "学习计划",
  task_state: "任务进展",
};

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
  toastTimer = setTimeout(() => node.classList.remove("is-visible"), 3600);
}

function showPage(name) {
  $$(".page").forEach((panel) => panel.classList.toggle("is-active", panel.dataset.pagePanel === name));
  $$(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.page === name));
  if (name === "library") {
    loadDocuments();
    loadMemory();
  }
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

function kindLabel(kind) {
  return KIND_LABELS[kind] || kind || "其他";
}

/* ---------------- health + stats ---------------- */

async function loadHealth() {
  try {
    const data = await api("/health");
    const seekdb = data.integrations.seekdb;
    const powercontext = data.integrations.powercontext || {};
    const memory = powercontext.ready ? "记忆已连接" : "记忆未连接";
    if (seekdb.status === "ok") {
      setStatus("is-ok", `seekdb · ${seekdb.chunks} chunks · ${memory}`);
    } else {
      setStatus("is-bad", `seekdb 异常 · ${memory}`);
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
    <div><strong id="ask-due">${state.review?.stats?.due ?? "—"}</strong>今日待复习</div>
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

/* ---------------- memory ---------------- */

async function loadMemory() {
  const list = $("#memory-list");
  const empty = $("#memory-empty");
  try {
    const [status, payload] = await Promise.all([
      api("/api/memory/status"),
      api(`/api/memory?session_id=${encodeURIComponent(state.sessionId)}&limit=100`),
    ]);
    state.memories = payload.memories || [];
    renderMemoryStats(status);
    renderMemoryList(state.memories);
    empty.hidden = state.memories.length > 0;
    if (!list.children.length) list.innerHTML = "";
  } catch (error) {
    $("#memory-stats").innerHTML = "";
    list.innerHTML = `<div class="memory-error">记忆读取失败：${escapeHtml(error.message)}。<br>请先启动 PowerContext：scripts/start_powercontext.*</div>`;
    empty.hidden = true;
  }
}

function renderMemoryStats(status) {
  const kinds = status.kinds || {};
  $("#memory-stats").innerHTML = `
    <div class="stat-card"><div class="stat-value">${status.memories ?? 0}</div><div class="stat-label">记忆总数</div></div>
    <div class="stat-card"><div class="stat-value">${kinds.weakness ?? 0}</div><div class="stat-label">薄弱点</div></div>
    <div class="stat-card"><div class="stat-value">${kinds.profile ?? 0}</div><div class="stat-label">学习偏好</div></div>
    <div class="stat-card"><div class="stat-value">${kinds.session_summary ?? 0}</div><div class="stat-label">会话摘要</div></div>
  `;
}

function renderMemoryList(memories) {
  const list = $("#memory-list");
  if (!memories.length) {
    list.innerHTML = "";
    return;
  }
  list.innerHTML = memories.map((memory) => `
    <article class="memory-row">
      <div class="memory-top">
        <span class="kind-badge ${escapeHtml(memory.kind)}">${escapeHtml(kindLabel(memory.kind))}</span>
        <span class="mono">${escapeHtml(memory.artifact_id || "")}</span>
      </div>
      <p>${escapeHtml(memory.text)}</p>
    </article>
  `).join("");
}

/* ---------------- ask ---------------- */

function setMode(mode) {
  state.mode = mode;
  $$(".seg").forEach((button) => button.classList.toggle("is-active", button.dataset.mode === mode));
}

async function ask(question, sessionId) {
  return api("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      session_id: sessionId,
      mode: state.mode,
      subject: $("#subject-filter").value || null,
      top_k: 8,
    }),
  });
}

async function runAsk(queryOverride, options = {}) {
  const input = $("#query-input");
  const query = (queryOverride ?? input.value).trim();
  if (!query) {
    input.focus();
    return null;
  }
  if (state.busy) return null;
  input.value = query;
  state.busy = true;
  state.lastQuestion = query;
  $("#search-btn").disabled = true;
  $("#search-btn").textContent = "回答中…";
  $("#ask-empty").hidden = true;
  $("#closeout-result").hidden = true;

  const started = performance.now();
  try {
    const data = await ask(query, state.sessionId);
    const elapsed = Math.round(performance.now() - started);
    if (!options.silent) {
      renderAsk(data, elapsed);
      await loadTraces();
    }
    return data;
  } catch (error) {
    if (!options.silent) {
      $("#search-meta").hidden = false;
      $("#search-meta").innerHTML = `<span>回答失败</span><span class="meta-note">${escapeHtml(error.message)}</span>`;
      $("#results").innerHTML = "";
      $("#answer-panel").hidden = true;
    }
    toast(`回答失败：${error.message}`);
    return null;
  } finally {
    state.busy = false;
    $("#search-btn").disabled = false;
    $("#search-btn").textContent = "提问并回答";
  }
}

function renderAsk(data, elapsed) {
  state.lastAsk = data;
  const meta = $("#search-meta");
  meta.hidden = false;
  const modeLabel = { hybrid: "混合检索", vector: "仅向量", fulltext: "仅全文" }[data.mode] || data.mode;
  meta.innerHTML = `
    <span><strong>${escapeHtml(modeLabel)}</strong></span>
    <span>关键词：${escapeHtml((data.keywords || []).join("、") || "无")}</span>
    <span class="mono">${elapsed} ms · ${escapeHtml(data.trace_ids?.answer || "")}</span>
    <span class="meta-note">${escapeHtml((data.notes || []).join("；"))}</span>
  `;

  renderAnswer(data, elapsed);
  renderResults(data);
}

function citationize(text) {
  return escapeHtml(text).replace(/\[(\d+)\]/g, '<span class="cite-num">[$1]</span>');
}

function renderAnswer(data, elapsed) {
  const panel = $("#answer-panel");
  panel.hidden = false;
  const modeText = data.mode === "llm" ? "LLM 生成 · 依据检索证据" : "证据模式 · 未配置 LLM，直接摘录原文";
  $("#answer-mode").textContent = modeText;
  $("#answer-mode").className = `answer-mode ${data.mode}`;
  $("#answer-timing").textContent =
    `检索 ${data.timing_ms?.retrieval ?? 0} ms · 记忆 ${data.timing_ms?.memory ?? 0} ms · 前端 ${elapsed} ms`;

  $("#answer-body").innerHTML = String(data.answer || "")
    .split(/\n{2,}/)
    .filter(Boolean)
    .map((paragraph) => `<p>${citationize(paragraph).replace(/\n/g, "<br>")}</p>`)
    .join("");

  const injected = data.injected_memories || [];
  const block = $("#injected-memory");
  block.hidden = injected.length === 0;
  $("#injected-list").innerHTML = injected.map((memory) => `
    <div class="memory-chip ${escapeHtml(memory.kind)}">
      <span class="kind-badge ${escapeHtml(memory.kind)}">${escapeHtml(kindLabel(memory.kind))}</span>
      <p>${escapeHtml(memory.text)}</p>
      <span class="memory-score">${memory.score == null ? "列出" : `相关度 ${(memory.score * 100).toFixed(2)}`}</span>
    </div>
  `).join("");
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

/* ---------------- session close-out ---------------- */

function openCloseout() {
  const card = $("#closeout-card");
  card.hidden = false;
  $("#closeout-result").hidden = true;
  $("#closeout-struggles").value = "";
  $("#closeout-preference").value = "";
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  $("#closeout-struggles").focus();
}

function closeCloseout() {
  $("#closeout-card").hidden = true;
}

async function submitCloseout() {
  if (!state.lastAsk) {
    toast("先提一个问题，再结束本轮");
    return;
  }
  const button = $("#closeout-submit");
  button.disabled = true;
  button.textContent = "写入中…";
  try {
    const data = await api("/api/session/close", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.sessionId,
        topic: state.lastQuestion,
        struggles: $("#closeout-struggles").value.trim(),
        preference: $("#closeout-preference").value.trim(),
      }),
    });
    const written = (data.memories || []).map((memory) =>
      `<li><span class="kind-badge ${escapeHtml(memory.kind)}">${escapeHtml(kindLabel(memory.kind))}</span>${escapeHtml(memory.text)}</li>`
    ).join("");
    const result = $("#closeout-result");
    result.hidden = false;
    result.innerHTML = `
      <p class="closeout-ok">已写回 PowerContext：${data.memories.length} 条记忆</p>
      <ul class="closeout-memories">${written || "<li>没有新增记忆（内容已存在）</li>"}</ul>
      <p class="closeout-summary">${escapeHtml(data.summary)}</p>
    `;
    toast(`已结束本轮并写入 ${data.memories.length} 条记忆`);
    await loadMemory();
    await loadTraces();
  } catch (error) {
    toast(`收尾失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "结束本轮并写入记忆";
  }
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
    const data = await api(`/api/traces?limit=80`);
    const traces = data.traces || [];
    state.traces = traces.length;
    $("#trace-count").textContent = traces.length;
    const list = $("#trace-list");
    if (!traces.length) {
      list.innerHTML = `<div class="trace-empty">本会话还没有轨迹。提一个问题或导入一份资料，就能在这里看到 seekdb 与 PowerContext 的真实调用。</div>`;
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

/* ---------------- review + practice ---------------- */

function percent(value) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function masteryClass(value) {
  if (value == null) return "is-new";
  if (value < 0.45) return "is-weak";
  if (value < 0.7) return "is-mid";
  return "is-strong";
}

async function loadReview() {
  try {
    const data = await api(`/api/review/today?limit=10&session_id=${encodeURIComponent(state.sessionId)}`);
    state.review = data;
    renderReview(data);
  } catch (error) {
    $("#review-list").innerHTML = `<div class="memory-error">复习队列加载失败：${escapeHtml(error.message)}</div>`;
    $("#review-empty").hidden = true;
  }
}

function renderReview(data) {
  const stats = data.stats || {};
  const due = stats.due ?? 0;
  const askDue = $("#ask-due");
  if (askDue) askDue.textContent = due;
  const badge = $("#review-badge");
  if (badge) {
    badge.textContent = due;
    badge.hidden = !due;
  }
  $("#review-stats").innerHTML = `
    <div class="stat-card"><div class="stat-value">${stats.due ?? 0}</div><div class="stat-label">今日待复习</div></div>
    <div class="stat-card"><div class="stat-value">${stats.new ?? 0}</div><div class="stat-label">未练习知识点</div></div>
    <div class="stat-card"><div class="stat-value">${percent(stats.average)}</div><div class="stat-label">平均掌握度 · 薄弱 ${stats.weak ?? 0}</div></div>
    <div class="stat-card"><div class="stat-value">${stats.answered_today ?? 0}</div><div class="stat-label">今日已答 · 正确 ${stats.correct_today ?? 0}</div></div>
  `;

  const queue = data.queue || [];
  const list = $("#review-list");
  const empty = $("#review-empty");
  if (!queue.length) {
    list.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  list.innerHTML = queue.map((row) => {
    const value = row.score;
    return `
      <article class="review-row">
        <div class="review-main">
          <div class="review-top">
            <span class="subject-tag">${escapeHtml(row.subject)}</span>
            <span class="review-state ${row.state === "new" ? "is-new" : "is-due"}">${row.state === "new" ? "未练习" : "到期"}</span>
            <span class="mono">${escapeHtml(row.kp_id)}</span>
          </div>
          <p class="review-name">${escapeHtml(row.name)}</p>
          <p class="review-section">${escapeHtml(row.section)}</p>
        </div>
        <div class="review-side">
          <div class="review-score-row">
            <span class="review-side-label">掌握度</span>
            <span class="review-score">${percent(value)}</span>
          </div>
          <div class="mastery-bar"><div class="mastery-fill ${masteryClass(value)}" style="width:${value == null ? 0 : Math.max(3, Math.round(value * 100))}%"></div></div>
          <span class="review-next">${escapeHtml(row.next_review_label)}</span>
          <span class="review-chunks">${row.chunk_count} chunks</span>
        </div>
      </article>
    `;
  }).join("");
}

async function buildPlan() {
  const button = $("#plan-btn");
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "生成中…";
  try {
    const data = await api("/api/review/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, days: 3, limit: 5 }),
    });
    const output = $("#plan-output");
    output.hidden = false;
    output.innerHTML = `
      <div class="plan-head">
        <strong>未来 3 天计划</strong>
        <span class="plan-badge">${data.reused ? "复用已有 PowerContext · plan" : "已写入 PowerContext · plan"}</span>
      </div>
      <p>${escapeHtml(data.plan)}</p>
      <p class="plan-meta">${data.queue.length} 个知识点 · trace ${escapeHtml(data.trace_id)} · memory ${escapeHtml(data.memories?.[0]?.artifact_id || "—")}</p>
    `;
    toast(data.reused ? "计划已存在，直接复用" : "已生成 3 天计划并写入 PowerContext");
    await loadMemory();
    await loadTraces();
  } catch (error) {
    toast(`生成计划失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function updateQuizProgress() {
  if (!state.quiz) return;
  const total = state.quiz.data.questions.length;
  const answered = Object.keys(state.quiz.answers).length;
  $("#quiz-progress").textContent = `已答 ${answered} / ${total}`;
}

function renderQuiz() {
  const questions = state.quiz.data.questions;
  const uniquePoints = new Set(questions.map((item) => item.kp_id)).size;
  $("#quiz-title").textContent = questions.length >= 20 ? "20 题模拟" : "今日练习";
  $("#quiz-hint").textContent = `共 ${questions.length} 题，覆盖 ${uniquePoints} 个知识点；题目由 seekdb 原文自动生成，提交后展示出处与解释。`;
  $("#quiz-progress").textContent = `已答 0 / ${questions.length}`;
  $("#quiz-body").innerHTML = questions.map((question, index) => `
    <article class="quiz-item" data-qid="${escapeHtml(question.question_id)}">
      <div class="quiz-index">${index + 1}</div>
      <div class="quiz-content">
        <p class="quiz-prompt">${escapeHtml(question.prompt).replace(/\n/g, "<br>")}</p>
        <div class="quiz-options">
          ${question.options.map((option, optionIndex) => `
            <label class="quiz-option">
              <input type="radio" name="q-${escapeHtml(question.question_id)}" value="${escapeHtml(option)}" data-qid="${escapeHtml(question.question_id)}">
              <span class="quiz-letter">${String.fromCharCode(65 + optionIndex)}</span>
              <span class="quiz-option-text">${escapeHtml(option)}</span>
            </label>
          `).join("")}
        </div>
        <p class="quiz-source-hint">${question.question_type === "excerpt_to_kp" ? "原文归属题" : "原文匹配题"} · ${escapeHtml(question.subject)}</p>
      </div>
    </article>
  `).join("");
  $("#quiz-result").hidden = true;
}

async function openQuiz(limit) {
  const button = $(limit >= 20 ? "#quiz-sim" : "#quiz-start");
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "生成中…";
  try {
    const session = state.sessionId;
    const data = await api("/api/quiz/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit, session_id: session }),
    });
    if (!data.questions.length) {
      toast("没有生成题目：资料库还没有可用的章节");
      return;
    }
    state.quizSession = session;
    state.quiz = { data, answers: {}, submitted: false };
    $("#quiz-note").value = "";
    $("#quiz-submit").disabled = false;
    $("#quiz-submit").textContent = "提交并更新掌握度";
    renderQuiz();
    $("#quiz-panel").hidden = false;
    $("#quiz-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    toast(`生成练习失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function closeQuiz() {
  $("#quiz-panel").hidden = true;
  state.quiz = null;
}

async function submitQuiz(event) {
  event.preventDefault();
  if (!state.quiz || state.quiz.submitted) return;
  const answers = Object.entries(state.quiz.answers).map(([questionId, chosen]) => ({
    question_id: questionId,
    chosen,
  }));
  if (!answers.length) {
    toast("先选至少一道题的答案");
    return;
  }
  const button = $("#quiz-submit");
  button.disabled = true;
  button.textContent = "判分中…";
  try {
    const data = await api("/api/quiz/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.quizSession,
        note: $("#quiz-note").value.trim(),
        answers,
      }),
    });
    state.quiz.submitted = true;
    renderQuizResult(data);
    $$("#quiz-body input").forEach((input) => (input.disabled = true));
    button.textContent = "已提交";
    toast(`已完成 ${data.score.total} 题，正确 ${data.score.correct} 题`);
    await loadReview();
    await loadMemory();
    await loadTraces();
  } catch (error) {
    toast(`提交失败：${error.message}`);
    button.disabled = false;
    button.textContent = "提交并更新掌握度";
  }
}

function renderQuizResult(data) {
  const container = $("#quiz-result");
  container.hidden = false;
  const score = data.score || {};
  const results = data.results || [];
  const memories = data.memories || [];
  container.innerHTML = `
    <div class="quiz-score">
      <div><strong>${score.correct ?? 0} / ${score.total ?? 0}</strong><span>正确率 ${percent(score.accuracy)}</span></div>
      <span class="quiz-memory-state ${data.memory_error ? "is-bad" : "is-ok"}">
        ${data.memory_error ? `PowerContext 写入异常：${escapeHtml(data.memory_error)}` : `已写入 ${memories.length} 条 PowerContext 记忆`}
      </span>
    </div>
    <div class="quiz-result-list">
      ${results.map((item) => `
        <article class="quiz-result-row ${item.correct ? "is-correct" : "is-wrong"}">
          <div class="quiz-result-head">
            <span class="quiz-result-badge">${item.correct ? "答对" : "答错"}</span>
            <strong>${escapeHtml(item.kp_name)}</strong>
            <span class="mono">掌握度 ${percent(item.mastery_before)} → ${percent(item.mastery_after)}</span>
          </div>
          <p class="quiz-result-question">${escapeHtml(item.prompt).replace(/\n/g, "<br>")}</p>
          <p class="quiz-result-answer">你的答案：${escapeHtml(item.chosen || "未作答")}</p>
          <p class="quiz-result-answer is-correct-answer">正确答案：${escapeHtml(item.answer)}</p>
          <p class="quiz-result-explain">${escapeHtml(item.explanation)}</p>
          <p class="quiz-result-next">下次复习：${escapeHtml(item.next_review_label || formatDate(item.next_review_at))}</p>
        </article>
      `).join("")}
    </div>
    ${memories.length ? `
      <div class="quiz-memories">
        <h3>本轮写入 PowerContext 的记忆</h3>
        <ul>
          ${memories.map((memory) => `
            <li><span class="kind-badge ${escapeHtml(memory.kind)}">${escapeHtml(kindLabel(memory.kind))}</span>${escapeHtml(memory.text)}</li>
          `).join("")}
        </ul>
      </div>
    ` : ""}
  `;
}

/* ---------------- demo mode ---------------- */

const DEMO_ROUNDS = [
  {
    question: "我总是把 L1 和 L2 正则化搞混，PCA 为什么先中心化？",
    struggles: "L1 的稀疏解和 L2 的权重衰减总是记反，PCA 中心化的目的也说反了",
    preference: "先给一句话结论，再配一个中文例子",
  },
  {
    question: "怎么防止模型过拟合？",
    struggles: "正则化系数 lambda 怎么选还不确定，早停和权重衰减的关系也没理清",
    preference: "",
  },
  {
    question: "我上次在正则化上错在哪？",
    struggles: "",
    preference: "",
  },
];

async function runDemo() {
  const button = $("#demo-btn");
  const originalSession = state.sessionId;
  button.disabled = true;
  button.textContent = "演示中…";
  try {
    const seeded = await api("/api/ingest/seed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId }),
    });
    const imported = (seeded.results || []).filter((item) => !item.skipped).length;
    toast(imported ? `已导入 ${imported} 份示例资料` : "示例资料已存在，直接开始三次会话");
    await loadDocuments();

    showPage("ask");
    const base = `demo-${Date.now().toString(36)}`;
    let last = null;
    let lastElapsed = 0;
    for (let index = 0; index < DEMO_ROUNDS.length; index += 1) {
      const round = DEMO_ROUNDS[index];
      state.sessionId = `${base}-${index + 1}`;
      setMode("hybrid");
      $("#subject-filter").value = "";
      const started = performance.now();
      const data = await ask(round.question, state.sessionId);
      lastElapsed = Math.round(performance.now() - started);
      if (!data) throw new Error("演示问答失败");
      last = data;
      await api("/api/session/close", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: state.sessionId,
          topic: round.question,
          struggles: round.struggles,
          preference: round.preference,
        }),
      });
      if (index < DEMO_ROUNDS.length - 1) {
        toast(`第 ${index + 1} 轮已写入记忆，继续下一轮…`);
        await new Promise((resolve) => setTimeout(resolve, 520));
      }
    }
    $("#query-input").value = DEMO_ROUNDS[2].question;
    $("#ask-empty").hidden = true;
    renderAsk(last, lastElapsed);
    $("#answer-timing").textContent = "演示第三轮 · 已注入前两轮写入的偏好、薄弱点与摘要";
    await loadTraces();
    await loadMemory();
    setDrawer(true);
    toast("演示完成：第三轮回答已带上前两轮记忆，可在技术轨迹里核对");
  } catch (error) {
    toast(`演示失败：${error.message}`);
  } finally {
    state.sessionId = originalSession;
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
      runAsk();
    });
  });

  $("#search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runAsk();
  });

  $("#query-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      runAsk();
    }
  });

  $("#closeout-open").addEventListener("click", openCloseout);
  $("#closeout-close").addEventListener("click", closeCloseout);
  $("#closeout-cancel").addEventListener("click", closeCloseout);
  $("#closeout-submit").addEventListener("click", submitCloseout);

  $("#memory-refresh").addEventListener("click", loadMemory);

  $("#quiz-start").addEventListener("click", () => openQuiz(5));
  $("#quiz-sim").addEventListener("click", () => openQuiz(20));
  $("#review-refresh").addEventListener("click", loadReview);
  $("#plan-btn").addEventListener("click", buildPlan);
  $("#quiz-close").addEventListener("click", closeQuiz);
  $("#quiz-form").addEventListener("submit", submitQuiz);
  $("#quiz-body").addEventListener("change", (event) => {
    const input = event.target.closest("input[type=radio]");
    if (!input || !state.quiz) return;
    state.quiz.answers[input.dataset.qid] = input.value;
    $$(".quiz-option", input.closest(".quiz-item")).forEach((label) => {
      label.classList.toggle("is-selected", label.contains(input));
    });
    updateQuizProgress();
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
        body: JSON.stringify({ session_id: state.sessionId }),
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
    form.append("session_id", state.sessionId);
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
    if (event.key === "Escape") {
      if ($("#trace-drawer").classList.contains("is-open")) setDrawer(false);
      if (!$("#closeout-card").hidden) closeCloseout();
    }
  });
}

async function boot() {
  bindEvents();
  await loadHealth();
  await loadDocuments();
  await loadReview();
  await loadTraces();
}

boot();
