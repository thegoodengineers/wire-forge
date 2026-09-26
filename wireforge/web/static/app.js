"use strict";

// Everything that reaches the page from a run (URLs, site responses, model text) is untrusted:
// it only ever goes through esc() or textContent, never straight into innerHTML.
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
  return body;
};
const host = (u) => { try { return new URL(u).host.replace(/^www\./, ""); } catch { return u || ""; } };
const OUTCOME = { verified: "verified", rejected_by_verifier: "rejected", no_working_action: "no action", error: "error", running: "running", interrupted: "interrupted", done: "done" };

let meta = {};
let current = null; // { id, source }

// ------------------------------------------------------------------ router
const ROUTES = ["home", "board", "actions", "results", "safety"];
function route() {
  const h = location.hash.slice(1);
  const name = ROUTES.includes(h) ? h : "home";
  ROUTES.forEach((r) => ($(`#view-${r}`).hidden = r !== name));
  $$(".tabs a").forEach((a) => a.classList.toggle("on", a.dataset.route === name));
  if (!ROUTES.includes(h) && h) document.getElementById(h)?.scrollIntoView();
  else window.scrollTo(0, 0);
  if (name === "board") loadBoard();
  if (name === "actions") loadActions();
  if (name === "results") loadResults();
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ tally (only from bench/results.csv)
async function loadTally() {
  const t = await api("/api/tally").catch(() => null);
  if (!t) return;
  $$("[data-t]").forEach((el) => {
    const v = t[el.dataset.t];
    el.textContent = v === null || v === undefined || (t.runs === 0 && el.dataset.t !== "runs") ? "—" : `${v}${el.dataset.unit || ""}`;
  });
  $("#home-tally-empty").hidden = t.runs > 0;
  const rows = Object.entries(t.models);
  renderModelChart(rows);
  $("#home-models tbody").innerHTML = rows.length
    ? rows.map(([m, v]) => `<tr><td class="mono">${esc(m)}</td><td>${v.runs}</td><td>${v.verified}</td><td>${v.median_min ?? "—"}</td><td>${v.avg_repairs ?? "—"}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">No comparison runs yet.</td></tr>`;
}

function renderModelChart(rows) {
  // Bars come straight from /api/tally (which reads only bench/results.csv); no chart without data.
  const box = $("#model-chart");
  if (!box) return;
  box.hidden = rows.length < 1;
  if (box.hidden) return;
  const max = Math.max(...rows.map(([, v]) => v.median_min || 0), 0.1);
  $("#model-bars").innerHTML = rows.map(([m, v]) => {
    const slow = v.median_min === max && rows.length > 1;
    return `
    <div class="bar-row">
      <span class="bar-label mono">${esc(m)}</span>
      <div class="bar-track"><div class="bar-fill ${slow ? "part" : ""}" style="width:${Math.max(4, ((v.median_min || 0) / max) * 100)}%"></div></div>
      <span class="bar-value">${v.median_min != null ? `median ${esc(v.median_min)} min` : "—"} · ${v.verified}/${v.runs} verified${v.avg_repairs ? ` · ${esc(v.avg_repairs)} avg repairs` : ""}</span>
    </div>`;
  }).join("");
}

async function loadReferee() {
  // Catalog audits are ordinary runs in out/ whose ids start with wire-catalog__.
  const box = $("#referee-cards");
  if (!box) return;
  const runs = (await api("/api/runs").catch(() => [])).filter((r) => r.id.startsWith("wire-catalog__"));
  if (!runs.length) return;
  const cards = await Promise.all(runs.slice(0, 6).map(async (r) => {
    const d = await api(`/api/runs/${encodeURIComponent(r.id)}`).catch(() => null);
    const s = d?.summary, v = d?.verdict;
    if (!s) return "";
    return `<div class="a-card"><span class="status ${s.passed ? "verified" : "error"}">${s.passed ? "certified" : "failed audit"}</span>
      <h4>${esc(s.action_id)}</h4>
      <p>${esc(host(s.site))} · ${esc(s.matched)}/${esc(s.checks)} checks matched · ${esc(s.wall_s)}s</p>
      <p class="g">${esc((v?.summary || "").slice(0, 180))}…</p></div>`;
  }));
  box.innerHTML = cards.join("") || box.innerHTML;
}

async function loadMeta() {
  meta = await api("/api/meta").catch(() => ({}));
  $$('[data-meta="version"]').forEach((el) => (el.textContent = `v${meta.version || "?"}`));
  $$('[data-meta="browser"]').forEach((el) => (el.textContent = meta.browser || "—"));
  const sel = $("#model-select");
  const models = meta.models?.length ? meta.models : [meta.model, meta.baseline_model].filter(Boolean);
  sel.innerHTML = models
    .map((m) => `<option value="${esc(m)}">${esc(m)}${m === meta.baseline_model ? " (baseline)" : ""}</option>`).join("");
}

setInterval(() => ($("#clock").textContent = new Date().toLocaleTimeString()), 1000);

// ------------------------------------------------------------------ home: steps + faq
function initSteps() {
  const items = $$("#step-list li"), arts = $$(".step-body article");
  const on = (i) => items.forEach((li) => li.classList.toggle("on", +li.dataset.step === i));
  items.forEach((li) => li.addEventListener("click", () => arts[+li.dataset.step].scrollIntoView({ behavior: "smooth", block: "center" })));
  const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && on(+e.target.dataset.step)), { rootMargin: "-45% 0px -45% 0px" });
  arts.forEach((a) => io.observe(a));
}

const FAQ = [
  ["Is it safe to point at a real shop?", "Yes. It can add to a cart, never past it: checkout, payment and orders are blocked in code, and no passwords are ever used."],
  ["What do I actually get?", "A ready-to-use API for the site: the spec, working code and a test, plus the verifier's report showing it's correct."],
  ["How do you know the output is right?", "A second, independent AI runs it twice with its own inputs and compares the results with the live page."],
  ["What if the check fails?", "The builder gets the report and fixes it. Still failing after two repairs? The run is recorded as rejected, never quietly shipped."],
  ["How is the comparison fair?", "Same sites, same goals, same limits, same judge. Every number on this site comes from the recorded results file."],
  ["What does it run on?", "A laptop. A real browser, Claude Opus 5.5 and plain Python. No special infrastructure."],
];
function initFaq() {
  const q = $("#faq-q"), a = $("#faq-a");
  const show = (i) => {
    $$("li", q).forEach((li, j) => li.classList.toggle("on", i === j));
    a.innerHTML = `<h3>${esc(FAQ[i][0])}</h3><p>${esc(FAQ[i][1])}</p>`;
  };
  q.innerHTML = FAQ.map(([t]) => `<li tabindex="0">${esc(t)}</li>`).join("");
  $$("li", q).forEach((li, i) => {
    li.addEventListener("click", () => show(i));
    li.addEventListener("keydown", (e) => e.key === "Enter" && show(i));
  });
  show(0);
}

// ------------------------------------------------------------------ board
const PRESETS = [
  ["L1 · BMTC", "https://nammabmtcapp.karnataka.gov.in/", "list bus routes between two stops with timings"],
  ["L1 · VTU results", "https://results.vtu.ac.in/", "look up a student's semester results by USN"],
  ["L2 · RedBus", "https://www.redbus.in/", "search buses between two cities on a date, with fares and seats left"],
  ["L3 · Myntra", "https://www.myntra.com/", "search products by keyword with brand and price filters, paginated"],
  ["L4 · Snitch cart", "https://www.snitch.com/", "add a shirt in a given size and quantity to the cart"],
  ["Air quality · aqicn", "https://aqicn.org/city/delhi/", "live AQI and main pollutants for a given Indian city"],
  ["L5 · CPCB AQI", "https://airquality.cpcb.gov.in/ccr/", "live AQI and pollutant readings for a given city or station"],
];
function initBoard() {
  $("#presets").innerHTML = PRESETS.map(([l], i) => `<button type="button" data-i="${i}">${esc(l)}</button>`).join("");
  $$("#presets button").forEach((b) => b.addEventListener("click", () => {
    const [, url, goal] = PRESETS[+b.dataset.i];
    $("#run-form").url.value = url;
    $("#run-form").goal.value = goal;
  }));
  $("#run-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, msg = $("#form-msg"), btn = $("#run-btn");
    msg.className = "form-msg";
    msg.textContent = "Starting…";
    btn.disabled = true;
    try {
      const { id } = await api("/api/runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: f.url.value.trim(), goal: f.goal.value.trim(), model: f.model.value, passcode: f.passcode.value }),
      });
      msg.textContent = "Running. Watch it on the right.";
      await loadRuns();
      watch(id);
    } catch (err) {
      msg.className = "form-msg err";
      msg.textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  });
}

async function loadBoard() {
  await Promise.all([loadTally(), loadRuns()]);
}

async function loadRuns() {
  const runs = await api("/api/runs").catch(() => []);
  const ul = $("#run-list");
  if (!runs.length) { ul.innerHTML = `<li class="empty">No runs yet.</li>`; return runs; }
  ul.innerHTML = runs.map((r) => {
    const st = r.status === "done" ? r.outcome : r.status;
    return `<li data-id="${esc(r.id)}" class="${current?.id === r.id ? "on" : ""}">
      <div class="t"><span>${esc(host(r.url))}</span><span class="status ${esc(st)}">${esc(OUTCOME[st] || st)}</span></div>
      <div class="g">${esc(r.goal)}</div><div class="g mono">${esc(r.model)}</div></li>`;
  }).join("");
  $$("li[data-id]", ul).forEach((li) => li.addEventListener("click", () => watch(li.dataset.id)));
  if (!current && runs[0]) watch(runs.find((r) => r.status === "running")?.id || runs[0].id);
  return runs;
}

function setStage(name, cls) {
  const order = ["trace", "endpoint", "emit", "verify", "done"];
  const idx = order.indexOf(name);
  $$("#live-stages li").forEach((li, i) => {
    li.className = i < idx ? "ok" : i === idx ? cls : "";
  });
}

function watch(id) {
  if (current?.source) current.source.close();
  current = { id, source: null };
  $$("#run-list li").forEach((li) => li.classList.toggle("on", li.dataset.id === id));
  $("#feed").innerHTML = "";
  $("#spec-card").innerHTML = `<p class="panel-title">Action</p><p class="empty">Appears when the forge emits.</p>`;
  $("#verdict-card").innerHTML = `<p class="panel-title">Verifier</p><p class="empty">Appears when the verifier decides.</p>`;
  setStage("trace", "");
  api(`/api/runs/${encodeURIComponent(id)}`).then((d) => {
    const req = d.request || {};
    $("#live-title").textContent = `${host(req.url)} · ${req.goal || ""}`;
    $("#live-sub").textContent = `${req.model || ""} · verifier ${req.verifier_model || ""} · ${id}`;
    setStatus(d.status === "done" ? d.summary?.outcome : d.status);
  }).catch(() => {});
  const es = new EventSource(`/api/runs/${encodeURIComponent(id)}/events`);
  current.source = es;
  es.onmessage = (m) => { try { onEvent(id, JSON.parse(m.data)); } catch { /* partial line */ } };
  es.addEventListener("end", () => { es.close(); refreshDetail(id); loadRuns(); loadTally(); });
}

function setStatus(st) {
  const el = $("#live-status");
  el.className = `status ${st || ""}`;
  el.textContent = OUTCOME[st] || st || "";
}

function onEvent(id, ev) {
  if (current?.id !== id) return;
  const d = ev.data || {};
  const feed = $("#feed");
  const stick = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;
  const div = document.createElement("div");
  div.className = `ev ${esc(ev.agent)}`;
  const who = `<span class="who">${esc(ev.agent)}</span>`;

  if (ev.kind === "stage") {
    div.classList.add("stage");
    if (d.stage === "error") div.classList.add("error");
    div.innerHTML = `${who}${esc(stageText(d))}`;
    if (d.stage === "trace" || d.stage === "start") setStage("trace", "on");
    if (d.stage === "verify") setStage("verify", "on");
    if (d.stage === "repair") setStage("emit", "on");
    if (d.stage === "done") { setStage("done", d.outcome === "verified" ? "ok" : "bad"); setStatus(d.outcome); }
    if (d.stage === "error") { setStatus("error"); $$("#live-stages li.on").forEach((li) => (li.className = "bad")); }
  } else if (ev.kind === "tool") {
    const args = JSON.stringify(d.input || {});
    div.innerHTML = `${who}<details><summary>${esc(d.name)}(${esc(args.length > 110 ? args.slice(0, 110) + "…" : args)})${d.error ? " · error" : ""}</summary><pre>${esc(d.result)}</pre></details>`;
    if (d.error) div.classList.add("error");
    if (ev.agent === "forge" && (d.name === "network_detail" || d.name === "http_request")) setStage("endpoint", "on");
    if (d.name === "emit_action") {
      const ok = String(d.result).startsWith("Action PASSED");
      setStage(ok ? "verify" : "emit", ok ? "" : "on");
      refreshDetail(id);
    }
    if (d.name === "submit_verdict") refreshDetail(id);
  } else if (ev.kind === "thinking") {
    div.classList.add("thinking");
    div.innerHTML = `${who}${esc(String(d).slice(0, 600))}`;
  } else if (ev.kind === "text") {
    div.innerHTML = `${who}${esc(d)}`;
  } else if (ev.kind === "stats") {
    div.innerHTML = `${who}<span class="mono small">${esc(`${d.turns} turns · ${d.tool_calls} tool calls · ${d.output_tokens} output tokens · ${d.wall_s}s · stop: ${d.stop}`)}</span>`;
  } else if (ev.kind === "task") {
    div.innerHTML = `${who}<details><summary>task</summary><pre>${esc(d)}</pre></details>`;
  } else {
    return;
  }
  feed.appendChild(div);
  if (stick) feed.scrollTop = feed.scrollHeight;
}

function stageText(d) {
  switch (d.stage) {
    case "start": return `Start · ${d.url} · ${d.model}`;
    case "trace": return `Tracing the site in ${d.browser}`;
    case "verify": return `Verifying ${d.action_id} in a fresh browser`;
    case "repair": return `Verifier rejected it · repair round ${d.round}`;
    case "done": return `Done · ${OUTCOME[d.outcome] || d.outcome}`;
    case "error": return `Run failed · ${d.error}`;
    default: return d.stage;
  }
}

async function refreshDetail(id) {
  const d = await api(`/api/runs/${encodeURIComponent(id)}`).catch(() => null);
  if (!d || current?.id !== id) return;
  if (d.spec) $("#spec-card").innerHTML = `<p class="panel-title">Action</p>${specHtml(d.spec, d.test_params)}`;
  if (d.verdict) $("#verdict-card").innerHTML = `<p class="panel-title">Verifier</p>${verdictHtml(d.verdict)}`;
}

function specHtml(s, tp) {
  const params = (s.parameters || []).map((p) => `<tr><td class="mono">${esc(p.name)}</td><td>${esc(p.type)}${p.required ? " *" : ""}</td><td>${esc(p.description)}</td></tr>`).join("");
  return `<h4>${esc(s.action_id)}</h4>
    <p class="kv">${esc(s.name)} · <b>${esc(s.type)}</b></p>
    <p class="kv">${esc(s.description)}</p>
    <table class="params">${params}</table>
    ${(s.endpoints || []).length ? `<pre>${esc(s.endpoints.join("\n"))}</pre>` : ""}
    ${tp ? `<details><summary class="small mono">test_params</summary><pre>${esc(JSON.stringify(tp, null, 1))}</pre></details>` : ""}`;
}

function verdictHtml(v) {
  const checks = (v.checks || []).map((c) => `<div class="check"><span class="m ${c.match ? "y" : "n"}">${c.match ? "✓" : "✗"}</span>
    <div>${esc(c.what)}<small>action: ${esc(c.action_value)} · page: ${esc(c.page_value)}${c.note ? ` · ${esc(c.note)}` : ""}</small></div></div>`).join("");
  return `<p class="kv"><span class="status ${v.passed ? "verified" : "error"}">${v.passed ? "passed" : "rejected"}</span></p>
    <p class="kv">${esc(v.summary)}</p>${checks}`;
}

// ------------------------------------------------------------------ actions
async function loadActions() {
  const runs = (await api("/api/runs").catch(() => [])).filter((r) => r.action_id);
  const grid = $("#actions-grid");
  grid.innerHTML = runs.length ? runs.map((r) => {
    const st = r.status === "done" ? r.outcome : r.status;
    return `<div class="a-card" data-id="${esc(r.id)}" tabindex="0"><span class="status ${esc(st)}">${esc(OUTCOME[st] || st)}</span>
      <h4>${esc(r.action_id)}</h4><p>${esc(host(r.url))} · ${esc(r.type)} · ${esc(r.model)}</p></div>`;
  }).join("") : `<p class="empty">No actions yet. Start one on the Forge Board.</p>`;
  $$(".a-card", grid).forEach((c) => c.addEventListener("click", () => showAction(c.dataset.id)));
}

async function showAction(id) {
  $$(".a-card").forEach((c) => c.classList.toggle("on", c.dataset.id === id));
  const d = await api(`/api/runs/${encodeURIComponent(id)}`);
  const box = $("#action-detail");
  box.hidden = false;
  box.innerHTML = `<div class="detail-grid">
    <div>${d.spec ? specHtml(d.spec, d.test_params) : ""}
      ${d.spec ? `<details><summary class="small mono">return_schema</summary><pre>${esc(JSON.stringify(d.spec.return_schema, null, 1))}</pre></details>` : ""}
      <div class="side-card" style="margin-top:14px"><p class="panel-title">Verifier</p>${d.verdict ? verdictHtml(d.verdict) : `<p class="empty">Not verified.</p>`}</div></div>
    <div><p class="panel-title">action.py</p><pre style="max-height:640px">${esc(d.code || "")}</pre></div></div>`;
  box.scrollIntoView({ behavior: "smooth" });
}

// ------------------------------------------------------------------ results
async function loadResults() {
  const rows = await api("/api/results").catch(() => []);
  $("#results-table tbody").innerHTML = rows.length ? rows.map((r) => `<tr>
    <td class="mono">${esc(r.timestamp)}</td><td>${esc(host(r.site))}</td><td class="mono">${esc(r.model)}</td>
    <td><span class="status ${esc(r.outcome)}">${esc(OUTCOME[r.outcome] || r.outcome)}</span></td><td class="mono">${esc(r.action_id)}</td>
    <td>${esc(r.emits)}</td><td>${esc(r.repair_rounds)}</td><td>${esc(r.forge_turns)}</td>
    <td>${esc(r.verifier_matched)}/${esc(r.verifier_checks)}</td><td>${(Number(r.wall_s) / 60).toFixed(1)}</td></tr>`).join("")
    : `<tr><td colspan="10" class="empty">No runs recorded yet.</td></tr>`;
}

// ------------------------------------------------------------------ live chip (only a real running run)
async function loadLiveChip() {
  const runs = await api("/api/runs").catch(() => []);
  const r = runs.find((x) => x.status === "running");
  const chip = $("#live-chip");
  chip.hidden = !r;
  if (r) $("span", chip).textContent = `forging ${host(r.url)} now`;
}

// ------------------------------------------------------------------ head-to-head (bench/head2head receipts only)
const H2H_LABEL = { "wire-forge": "Wire Forge", "anakin-build-request": "Wire build-request", "wire-from-forge-spec": "Wire, rebuilt from our spec" };
const fmtSecs = (s) => (s == null ? "not shipped" : `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s`);

async function loadHead2Head() {
  const receipts = await api("/api/head2head").catch(() => []);
  const race = receipts.filter((r) => r.system === "wire-forge" || r.system === "anakin-build-request");
  if (!race.length) return;
  const max = Math.max(...race.map((r) => r.seconds_to_ship || 0), 1);
  const bySite = {};
  race.forEach((r) => (bySite[r.site] = bySite[r.site] || []).push(r));
  $("#h2h").innerHTML = Object.entries(bySite).map(([site, rs]) => {
    rs.sort((a, b) => (a.seconds_to_ship ?? 1e9) - (b.seconds_to_ship ?? 1e9));
    return `<div class="h2h-site"><p class="panel-title">${esc(site)} · ${esc(rs[0].goal)}</p>${rs.map((r, i) => `
      <div class="h2h-row ${r.system === "wire-forge" ? "us" : ""}">
        <div class="h2h-name">${esc(H2H_LABEL[r.system] || r.system)}${i === 0 && rs.length > 1 ? ' <span class="status verified">faster</span>' : ""}</div>
        <div class="h2h-bar"><i style="width:${((r.seconds_to_ship || 0) / max) * 100}%"></i><span class="mono">${esc(fmtSecs(r.seconds_to_ship))}</span></div>
        <dl class="h2h-facts">
          <dt>works</dt><dd>${r.works ? "yes" : "no"}</dd>
          <dt>inputs</dt><dd>${esc(r.inputs || "?")}</dd>
          <dt>verification</dt><dd>${esc(r.verification || "none")}</dd>
          <dt>cost</dt><dd>${esc(r.cost_per_call || "?")}</dd>
        </dl>
      </div>`).join("")}<p class="fine">One site, one run each. Sources: ${rs.map((r) => `<span class="mono">${esc(r.source || "")}</span>`).join(" · ")}</p></div>`;
  }).join("");
  const loop = receipts.find((r) => r.system === "wire-from-forge-spec");
  if (loop) {
    const box = $("#h2h-loop");
    box.hidden = false;
    box.innerHTML = `<p class="eyebrow">Then we handed it back</p>
      <h3>Wire rebuilt its action <em>from our verified spec.</em></h3>
      <p>${esc(loop.goal)}. Wire's catalog action <span class="mono">${esc(loop.action_id)}</span> now takes
      <b>${esc(loop.inputs)}</b>, shipped in ${esc(fmtSecs(loop.seconds_to_ship))}. ${esc(loop.verification)}.</p>`;
  }
}

// ------------------------------------------------------------------ boot
loadHead2Head();
initSteps();
initFaq();
initBoard();
loadMeta();
loadTally();
loadReferee();
route();
loadLiveChip();
setInterval(() => { if (location.hash === "#board") loadRuns(); loadTally(); loadLiveChip(); }, 15000);
