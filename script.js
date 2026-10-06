/* =========================================
   DataLens — Frontend JavaScript
   ========================================= */

// Empty = same address the page was opened from (the backend serves this page).
const API_BASE = "";

// ---- DOM refs ----
const sidebar       = document.getElementById("sidebar");
const sidebarToggle = document.getElementById("sidebarToggle");
const menuBtn       = document.getElementById("menuBtn");
const themeBtn      = document.getElementById("themeBtn");
const uploadZone    = document.getElementById("uploadZone");
const fileInput     = document.getElementById("fileInput");
const fileInfo      = document.getElementById("fileInfo");
const fileName      = document.getElementById("fileName");
const removeFile    = document.getElementById("removeFile");
const schemaSection = document.getElementById("schemaSection");
const schemaStats   = document.getElementById("schemaStats");
const schemaColumns = document.getElementById("schemaColumns");
const quickSection  = document.getElementById("quickSection");
const quickQuestions = document.getElementById("quickQuestions");
const landing       = document.getElementById("landing");
const workspace     = document.getElementById("workspace");
const welcomeCard   = document.getElementById("welcomeCard");
const welcomeMsg    = document.getElementById("welcomeMsg");
const insightsCard  = document.getElementById("insightsCard");
const insightsList  = document.getElementById("insightsList");
const conversation  = document.getElementById("conversation");
const questionInput = document.getElementById("questionInput");
const sendBtn       = document.getElementById("sendBtn");
const ctaUpload     = document.getElementById("ctaUpload");
const loadingOverlay = document.getElementById("loadingOverlay");
const loadingMsg    = document.getElementById("loadingMsg");
const resultsArea   = document.getElementById("resultsArea");
const sampleRow     = document.getElementById("sampleRow");
const sampleButtons = document.getElementById("sampleButtons");

// ---- State ----
let currentSchema = null;
let plotCounter = 0;
let openToken = 0;

// =========================================
// THEME TOGGLE
// =========================================
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  themeBtn.innerHTML = theme === "dark"
    ? '<i class="fas fa-sun"></i>'
    : '<i class="fas fa-moon"></i>';
}
themeBtn.addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme") ||
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = current === "dark" ? "light" : "dark";
  try { localStorage.setItem("datalens-theme", next); } catch (e) {}
  applyTheme(next);
});
// Init theme
try {
  const saved = localStorage.getItem("datalens-theme");
  if (saved) applyTheme(saved);
  else if (window.matchMedia("(prefers-color-scheme: dark)").matches) applyTheme("dark");
} catch (e) {}

// =========================================
// SIDEBAR TOGGLE
// =========================================
sidebarToggle.addEventListener("click", () => sidebar.classList.toggle("collapsed"));
menuBtn.addEventListener("click", () => sidebar.classList.toggle("open"));
// Close sidebar on outside click (mobile)
document.addEventListener("click", (e) => {
  if (window.innerWidth <= 768 && sidebar.classList.contains("open")) {
    if (!sidebar.contains(e.target) && !menuBtn.contains(e.target)) {
      sidebar.classList.remove("open");
    }
  }
});

// =========================================
// FILE UPLOAD
// =========================================
ctaUpload.addEventListener("click", () => fileInput.click());

// "View demo": load the sales sample and ask a few questions automatically.
const demoBtn = document.getElementById("demoBtn");
if (demoBtn) {
  demoBtn.addEventListener("click", async () => {
    await openDataset("sales.csv", `${API_BASE}/sample/sales.csv`, { method: "POST" });
    if (!currentSchema) return; // load failed, error already shown
    const demoQuestions = [
      "Top 3 products by revenue",
      "Monthly revenue trend",
      "Any outliers?",
    ];
    for (const q of demoQuestions) {
      questionInput.value = q;
      await sendQuestion();
    }
  });
}
uploadZone.addEventListener("click", () => fileInput.click());

// Drag & drop
uploadZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  uploadZone.classList.add("dragover");
});
uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("dragover"));
uploadZone.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadZone.classList.remove("dragover");
  if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});

fileInput.addEventListener("change", () => {
  if (fileInput.files.length) handleFile(fileInput.files[0]);
});

removeFile.addEventListener("click", () => {
  resetWorkspace();
});

async function handleFile(file) {
  const ext = file.name.split(".").pop().toLowerCase();
  if (!["csv", "xlsx", "xls"].includes(ext)) {
    alert("Please upload a CSV or Excel file.");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);
  openDataset(file.name, `${API_BASE}/upload`, { method: "POST", body: formData });
}

// Shared by file upload and the sample buttons.
async function openDataset(label, url, options) {
  resetWorkspace();
  const token = ++openToken;
  fileName.textContent = label;
  fileInfo.hidden = false;
  uploadZone.style.display = "none";
  showLoading("Reading & analyzing dataset…");

  try {
    let res;
    try {
      res = await fetch(url, options);
    } catch (e) {
      throw new Error("Can't reach the server. Start it with ./run.sh and open http://localhost:8000");
    }
    if (!res.ok) {
      throw new Error(await errorFromResponse(res, "Could not open the dataset"));
    }

    const data = await res.json();
    if (token !== openToken) return;
    currentSchema = data;
    showSchema(data.schema);
    showWorkspace(data);
  } catch (err) {
    if (token !== openToken) return;
    alert(err.message);
    resetWorkspace();
  } finally {
    if (token === openToken) hideLoading();
  }
}

// Sample datasets offered on the landing page
async function loadSampleList() {
  try {
    const names = await (await fetch(`${API_BASE}/samples`)).json();
    if (!names.length) return;
    names.forEach((name) => {
      const btn = document.createElement("button");
      btn.className = "sample-btn";
      btn.textContent = name;
      btn.addEventListener("click", () =>
        openDataset(name, `${API_BASE}/sample/${encodeURIComponent(name)}`, { method: "POST" })
      );
      sampleButtons.appendChild(btn);
    });
    sampleRow.hidden = false;
  } catch (e) {
    // Server not running: the upload button will explain when used.
  }
}
loadSampleList();

function resetWorkspace() {
  openToken++;
  hideLoading();
  currentSchema = null;
  fileInput.value = "";
  fileName.textContent = "—";
  fileInfo.hidden = true;
  uploadZone.style.display = "";
  schemaSection.hidden = true;
  quickSection.hidden = true;
  landing.hidden = false;
  workspace.hidden = true;
  welcomeCard.hidden = true;
  insightsCard.hidden = true;
  conversation.innerHTML = "";
}

// =========================================
// SCHEMA DISPLAY
// =========================================
function showSchema(schema) {
  // Stats
  schemaStats.innerHTML = `
    <div class="stat-box">
      <span class="stat-val">${schema.rows.toLocaleString()}</span>
      <span class="stat-label">Rows</span>
    </div>
    <div class="stat-box">
      <span class="stat-val">${schema.columns.length}</span>
      <span class="stat-label">Columns</span>
    </div>
    <div class="stat-box">
      <span class="stat-val">${schema.numeric_columns.length}</span>
      <span class="stat-label">Numeric</span>
    </div>
    <div class="stat-box">
      <span class="stat-val">${schema.missing_values}</span>
      <span class="stat-label">Missing</span>
    </div>
  `;

  // Columns
  schemaColumns.innerHTML = schema.column_details
    .map((col) => {
      let typeClass = "other";
      if (col.kind === "numeric") typeClass = "numeric";
      else if (col.kind === "categorical") typeClass = "text";
      else if (col.kind === "date") typeClass = "date";

      return `
        <div class="col-item">
          <span class="col-type ${typeClass}">${col.kind}</span>
          <span class="col-name">${escapeHtml(col.name)}</span>
        </div>
      `;
    })
    .join("");

  schemaSection.hidden = false;
}

// =========================================
// WORKSPACE (after upload)
// =========================================
function showWorkspace(data) {
  landing.hidden = true;
  workspace.hidden = false;
  welcomeCard.hidden = false;
  welcomeMsg.textContent = `${data.schema.rows} rows × ${data.schema.columns.length} columns loaded. Ask me anything!`;

  // Auto insights
  if (data.insights && data.insights.length) {
    insightsList.innerHTML = data.insights
      .map(
        (ins) => `
        <div class="insight-item">
          <i class="fas fa-chart-line"></i>
          <span>${formatAnswer(ins)}</span>
        </div>
      `
      )
      .join("");
    insightsCard.hidden = false;
  }

  // Quick questions
  if (data.suggested_questions && data.suggested_questions.length) {
    quickQuestions.innerHTML = data.suggested_questions
      .map(
        (q) => `
        <button class="quick-btn" data-question="${escapeAttr(escapeHtml(q))}">
          <i class="fas fa-circle-question"></i>${escapeHtml(q)}
        </button>
      `
      )
      .join("");
    quickSection.hidden = false;

    // Click handlers
    quickQuestions.querySelectorAll(".quick-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const q = btn.dataset.question;
        questionInput.value = q;
        sendQuestion();
      });
    });
  }

  // Focus input
  questionInput.focus();
}

// =========================================
// SEND QUESTION
// =========================================
questionInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendQuestion();
  }
});
sendBtn.addEventListener("click", sendQuestion);

async function sendQuestion() {
  const question = questionInput.value.trim();
  if (!question) return;
  if (!currentSchema) {
    alert("Please upload a dataset first.");
    return;
  }

  // Add user message
  addMessage("user", question);
  questionInput.value = "";
  sendBtn.disabled = true;

  // Show typing indicator
  const typingEl = addTypingIndicator();

  try {
    const res = await fetch(`${API_BASE}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    if (!res.ok) {
      throw new Error(await errorFromResponse(res, "Request failed"));
    }

    const data = await res.json();
    typingEl.remove();

    // Render answer
    renderAnswer(data);
  } catch (err) {
    typingEl.remove();
    addErrorMessage(err.message);
  } finally {
    sendBtn.disabled = false;
    questionInput.focus();
  }
}

// =========================================
// MESSAGE RENDERING
// =========================================
async function errorFromResponse(res, fallback) {
  const err = await res.json().catch(() => ({}));
  const d = err.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length) return d.map((x) => x.msg || JSON.stringify(x)).join("; ");
  return fallback;
}

function addMessage(role, text) {
  const row = document.createElement("div");
  row.className = `msg-row ${role}`;

  if (role === "user") {
    row.innerHTML = `
      <div class="msg-bubble">${escapeHtml(text)}</div>
      <div class="msg-avatar"><i class="fas fa-user"></i></div>
    `;
  } else {
    row.innerHTML = `
      <div class="msg-avatar"><i class="fas fa-robot"></i></div>
      <div class="msg-bubble">${text}</div>
    `;
  }

  conversation.appendChild(row);
  scrollToBottom();
}

function addTypingIndicator() {
  const row = document.createElement("div");
  row.className = "msg-row assistant";
  row.innerHTML = `
    <div class="msg-avatar"><i class="fas fa-robot"></i></div>
    <div class="msg-bubble">
      <div class="typing-dots"><span></span><span></span><span></span></div>
    </div>
  `;
  conversation.appendChild(row);
  scrollToBottom();
  return row;
}

function addErrorMessage(text) {
  const el = document.createElement("div");
  el.className = "error-msg";
  el.innerHTML = `<i class="fas fa-circle-exclamation"></i> ${escapeHtml(text)}`;
  conversation.appendChild(el);
  scrollToBottom();
}

function renderAnswer(data) {
  const row = document.createElement("div");
  row.className = "msg-row assistant";

  const card = document.createElement("div");
  card.className = "answer-card";

  // Text answer
  const textDiv = document.createElement("div");
  textDiv.className = "answer-text";
  textDiv.innerHTML = formatAnswer(data.answer);
  card.appendChild(textDiv);

  // Table (if present)
  if (data.table && data.table.length > 0) {
    const tableWrapper = document.createElement("div");
    tableWrapper.className = "answer-table-wrapper";
    tableWrapper.appendChild(buildTable(data.table));
    card.appendChild(tableWrapper);
  }

  // Chart (if present)
  if (data.chart) {
    const chartDiv = document.createElement("div");
    chartDiv.className = "answer-chart";
    const plotId = "plot-" + (++plotCounter);
    chartDiv.innerHTML = `<div id="${plotId}" style="width:100%;height:320px;"></div>`;
    card.appendChild(chartDiv);

    // Render chart after DOM insert
    setTimeout(() => renderChart(plotId, data.chart), 50);
  }

  // "How I got this": the exact steps behind the answer
  if (data.proof) {
    card.appendChild(buildProof(data.proof));
  }

  row.innerHTML = `<div class="msg-avatar"><i class="fas fa-robot"></i></div>`;
  row.appendChild(card);
  conversation.appendChild(row);
  scrollToBottom();
}

function buildProof(proof) {
  const details = document.createElement("details");
  details.className = "answer-proof";
  const summary = document.createElement("summary");
  summary.textContent = "How I got this";
  details.appendChild(summary);

  const rows = [
    ["Understood by", proof.engine === "claude" ? "Claude (saw column names only, never your rows)" : "Built-in rules (offline)"],
    ["Calculation", proof.operation],
    ["Columns used", proof.columns && proof.columns.length ? proof.columns.join(", ") : "All columns"],
    ["Rows used", Number(proof.rows_used).toLocaleString()],
    ["Plan", JSON.stringify(proof.plan)],
  ];
  if (proof.note) rows.push(["Note", proof.note]);

  const dl = document.createElement("dl");
  rows.forEach(([label, value]) => {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    dl.append(dt, dd);
  });
  details.appendChild(dl);
  return details;
}

function buildTable(rows) {
  if (!rows.length) return document.createElement("span");

  const table = document.createElement("table");
  table.className = "answer-table";

  // Header
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  const keys = Object.keys(rows[0]);
  keys.forEach((key) => {
    const th = document.createElement("th");
    th.textContent = key;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  // Body
  const tbody = document.createElement("tbody");
  rows.slice(0, 20).forEach((row) => {
    const tr = document.createElement("tr");
    keys.forEach((key) => {
      const val = row[key];
      const td = document.createElement("td");
      td.textContent = val !== null && val !== undefined ? val : "—";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);

  return table;
}

function renderChart(plotId, chartData) {
  const el = document.getElementById(plotId);
  if (!el) return;
  if (typeof Plotly === "undefined") {
    el.textContent = "Chart library failed to load (check your internet connection).";
    return;
  }

  // Determine if dark mode
  const isDark = document.documentElement.getAttribute("data-theme") === "dark" ||
    (!document.documentElement.getAttribute("data-theme") &&
     window.matchMedia("(prefers-color-scheme: dark)").matches);

  const layout = {
    ...chartData.layout,
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { color: isDark ? "#c8ccd4" : "#1a1d23", size: 12 },
    margin: { l: 50, r: 20, t: 40, b: 50 },
    xaxis: { ...chartData.layout?.xaxis, gridcolor: isDark ? "#2a2d35" : "#e2e5ea" },
    yaxis: { ...chartData.layout?.yaxis, gridcolor: isDark ? "#2a2d35" : "#e2e5ea" },
  };

  Plotly.newPlot(el, chartData.data, layout, {
    responsive: true,
    displayModeBar: false,
  });
}

// =========================================
// HELPERS
// =========================================
function formatAnswer(text) {
  // Convert **bold** and basic formatting
  return escapeHtml(text)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str) {
  return str.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function scrollToBottom() {
  resultsArea.scrollTop = resultsArea.scrollHeight;
}

function showLoading(msg) {
  loadingMsg.textContent = msg || "Analyzing…";
  loadingOverlay.hidden = false;
}

function hideLoading() {
  loadingOverlay.hidden = true;
}
