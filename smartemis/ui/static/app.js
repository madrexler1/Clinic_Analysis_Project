// Smartemis reviewer UI — vanilla JS, no build step.
const $ = (id) => document.getElementById(id);
const state = { currentReportId: null, selectedThumbs: null };

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status}: ${body}`);
  }
  return resp.json();
}

async function loadHealth() {
  try {
    const h = await api("/api/health");
    $("env-badge").textContent = `${h.env} · ${h.region}`;
  } catch (e) {
    $("env-badge").textContent = "offline";
  }
}

async function loadClinics() {
  try {
    const { clinics } = await api("/api/clinics");
    const select = $("clinic-select");
    select.innerHTML = "";
    for (const c of clinics) {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      select.appendChild(opt);
    }
  } catch (e) {
    $("generate-status").textContent = `Could not load clinics: ${e.message}`;
  }
}

async function loadRecent() {
  try {
    const list = await api("/api/reports?limit=30");
    const ul = $("recent-list");
    ul.innerHTML = "";
    for (const r of list) {
      const li = document.createElement("li");
      li.dataset.reportId = r.id;
      const net = r.net_feedback;
      const netClass = net > 0 ? "net-pos" : net < 0 ? "net-neg" : "";
      li.innerHTML = `
        <div>${r.clinic_site} <span class="${netClass}">${net >= 0 ? "+" : ""}${net}</span></div>
        <div class="meta">${new Date(r.created_at).toLocaleString()} · ${r.language.toUpperCase()}</div>
      `;
      li.addEventListener("click", () => loadReport(r.id));
      if (r.id === state.currentReportId) li.classList.add("active");
      ul.appendChild(li);
    }
  } catch (e) {
    console.error(e);
  }
}

function renderRubric(scores) {
  if (!scores || scores._parse_error) return "";
  const dims = ["NUMERIC_FIDELITY", "PEER_COMPARISON", "ACTIONABILITY", "CLARITY", "PII_COMPLIANCE"];
  const cells = dims
    .map((d) => {
      const entry = scores[d];
      if (!entry) return "";
      const score = entry.score ?? "?";
      return `<div class="cell"><div class="label">${d.replace(/_/g, " ")}</div><div class="score">${score}/5</div></div>`;
    })
    .join("");
  return `<div class="rubric">${cells}</div>`;
}

function renderFewShots(examples) {
  if (!examples || examples.length === 0) {
    return `<div class="few-shot-bar empty">
      <span class="label">Few-shot examples used:</span>
      <span class="muted">none — cold-start run (no thumbs-up'd reports yet, or set to 0)</span>
    </div>`;
  }
  const pills = examples.map((ex) => `
    <button class="few-shot-pill" data-id="${ex.id}" title="${escapeHtml(ex.snippet || "")}">
      <span class="pill-id">#${ex.id}</span>
      <span class="pill-clinic">${ex.clinic_site}</span>
      <span class="pill-score ${ex.net_score > 0 ? "pos" : ""}">+${ex.net_score}</span>
    </button>
  `).join("");
  return `<div class="few-shot-bar">
    <span class="label">Few-shot examples used (${examples.length}):</span>
    ${pills}
  </div>`;
}

function renderReport(r) {
  state.currentReportId = r.report_id ?? r.id;
  $("report-view").innerHTML = `
    <div class="meta-grid">
      <div class="cell"><div class="label">Clinic</div><div class="value">${r.clinic_site}</div></div>
      <div class="cell"><div class="label">Model</div><div class="value">${r.model_id.replace("eu.anthropic.", "")}</div></div>
      <div class="cell"><div class="label">Tokens in/out</div><div class="value">${r.input_tokens}/${r.output_tokens}</div></div>
      <div class="cell"><div class="label">Cache hit</div><div class="value">${r.cache_read_tokens}</div></div>
    </div>
    ${renderFewShots(r.few_shot_examples)}
    ${renderRubric(r.rubric_scores)}
    <pre>${escapeHtml(r.text)}</pre>
  `;
  // Wire pill clicks → load that past report
  document.querySelectorAll(".few-shot-pill").forEach((btn) => {
    btn.addEventListener("click", () => loadReport(Number(btn.dataset.id)));
  });
  $("feedback-panel").classList.remove("hidden");
  $("feedback-text").value = "";
  $("feedback-status").textContent = "";
  state.selectedThumbs = null;
  document.querySelectorAll(".thumb").forEach((b) => b.classList.remove("selected"));
  highlightActive();
}

function highlightActive() {
  document.querySelectorAll("#recent-list li").forEach((li) => {
    li.classList.toggle("active", Number(li.dataset.reportId) === state.currentReportId);
  });
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}

async function loadReport(id) {
  try {
    const r = await api(`/api/reports/${id}`);
    renderReport(r);
  } catch (e) {
    $("report-view").innerHTML = `<p class="muted">Failed to load: ${e.message}</p>`;
  }
}

async function generateReport() {
  const clinic = $("clinic-select").value;
  const few = Number($("few-shot").value);
  const score = $("auto-score").checked;
  if (!clinic) return;
  const btn = $("generate-btn");
  btn.disabled = true;
  $("generate-status").textContent = "Generating (this takes ~15-40s)...";
  try {
    const r = await api("/api/reports", {
      method: "POST",
      body: { clinic_site: clinic, few_shot_n: few, score_after_generate: score },
    });
    $("generate-status").textContent = "Done.";
    renderReport(r);
    loadRecent();
  } catch (e) {
    $("generate-status").textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
}

async function submitFeedback() {
  if (!state.currentReportId) return;
  const reviewer = $("reviewer-name").value.trim();
  if (!reviewer) {
    $("feedback-status").textContent = "Enter a reviewer name first.";
    return;
  }
  const thumbs = state.selectedThumbs || "none";
  const comment = $("feedback-text").value.trim() || null;
  try {
    await api(`/api/reports/${state.currentReportId}/feedback`, {
      method: "POST",
      body: { reviewer, thumbs, comment },
    });
    $("feedback-status").textContent = "Feedback saved.";
    loadRecent();
  } catch (e) {
    $("feedback-status").textContent = `Error: ${e.message}`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadHealth();
  loadClinics();
  loadRecent();

  $("generate-btn").addEventListener("click", generateReport);
  $("submit-feedback").addEventListener("click", submitFeedback);

  document.querySelectorAll(".thumb").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".thumb").forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
      state.selectedThumbs = btn.dataset.value;
    });
  });

  setInterval(loadRecent, 30000);
});
