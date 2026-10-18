// Fraud-monitor dashboard. Reads the orchestrator (/api) and renders the engagement list, timeline,
// indicators, and the captured decoy persona. Everything is built with createElement/textContent so
// scammer-supplied strings are never parsed as HTML. Internal tool — not linked from the bait site.
import { h, money, shortDate } from "./ui.js";

const API = "/api";
const inboxEl = document.getElementById("inbox");
const panelEl = document.getElementById("panel");
const countEl = document.getElementById("count");
const verdictEl = document.getElementById("verdict");
let selected = null;      // engagement id shown in the detail section
let selectedMsg = null;   // inbox message id of the selected row
let messages = [];
let engagements = [];
let detailSig = "";       // skip re-rendering the detail when nothing changed
let frame = null;         // index of the screenshot being viewed (null = follow live)
let inspect = null;       // id of the terminal event opened in the inspector
let story = null;         // story stage the user opened (null = follow the latest one)

async function api(path, opts) {
  const r = await fetch(API + path, opts);
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

const riskClass = (n) => (n >= 60 ? "risk-hi" : n >= 30 ? "risk-md" : "risk-lo");
const fmtTime = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }); };

async function renderStatus() {
  try {
    const st = await api("/status");
    const strip = document.getElementById("status");
    const cls = (m) => (["live", "app_password", "oauth"].includes(m) ? "live"
      : m === "polling" || m === "local" ? "local" : "fake");  // 'missing' shows grey
    const mark = { live: "✓", local: "~", fake: "✕" };
    const chip = (name, mode) => h("span", { class: `svc ${cls(mode)}` },
      h("span", { class: "mark" }, mark[cls(mode)]), `${name}: ${mode}`);
    strip.replaceChildren(...Object.entries(st.services).map(([k, v]) => chip(k, v)));
  } catch { /* status is best-effort */ }
}

// One row per inbound email, carrying the engagement (sandbox run) that judged it. Engagements
// that were started without an inbox message (API-driven runs) get a row of their own.
function rows() {
  const byId = Object.fromEntries(engagements.map((e) => [e.id, e]));
  const seen = new Set();
  const out = messages.map((m) => { seen.add(m.engagement_id); return { m, e: byId[m.engagement_id] || null }; });
  for (const e of engagements) if (!seen.has(e.id)) out.push({ m: null, e });
  return out;
}

const isSel = ({ m, e }) => (m ? m.id === selectedMsg : e.id === selected);

let inboxSig = "";
function renderInbox() {
  const list = rows();
  document.getElementById("inbox-count").textContent =
    `${messages.length} detonated · ${messages.filter((m) => m.verdict === "scam").length} scam` +
    (messages.some((m) => m.verdict === "pending") ? ` · ${messages.filter((m) => m.verdict === "pending").length} running` : "");
  const sig = list.map(({ m, e }) => `${m?.id}:${m?.verdict}:${e?.id}:${e?.status}:${e?.risk_score}:${(e?.tags || []).join(",")}:${isSel({ m, e })}`).join("|");
  if (sig === inboxSig) return;
  const first = !inboxSig;
  inboxSig = sig;
  inboxEl.replaceChildren(...list.map((row, i) => {
    const { m, e } = row;
    const verdict = m ? m.verdict : e.status === "active" ? "pending" : "error";
    const cls = { scam: "scam", safe: "safe", pending: "pending" }[verdict] || "review";
    return h("button", { class: `msg ${cls} ${isSel(row) ? "sel" : ""} ${first ? "enter" : ""}`,
      style: first ? `animation-delay:${Math.min(i, 20) * 25}ms` : null, onClick: () => open(row) },
      h("span", { class: "vtag" }, verdict === "pending" ? "running" : verdict === "error" ? "review" : verdict),
      h("div", { style: "min-width:0" },
        h("div", { class: "msub" }, m?.subject || e?.subject || "(no subject)"),
        h("div", { class: "mfrom" }, (m?.sender || e?.scammer_email || "") + (m?.vector ? ` · ${m.vector}` : "")),
        e ? h("div", { class: "mstate" },
          h("span", {}, h("span", { class: `sdot ${e.status}` }), e.status),
          ...(e.tags || []).map((t) => h("span", { class: "pill danger" }, t.replace(/_/g, " ")))) : null),
      h("span", { class: `risk ${riskClass(e?.risk_score || 0)}` }, e ? String(e.risk_score) : ""),
      h("span", { class: "maction" }, m?.action || ""));
  }));
}

const msgClass = (m) => ({ scam: "scam", safe: "safe", pending: "pending" }[m.verdict] || "review");
const _VERDICT = {
  scam: ["⚠ scam", "quarantined. Following the email in the sandbox cost the decoy victim — that's the evidence."],
  safe: ["✓ safe", "delivered. The decoy victim followed the email in the sandbox and lost nothing."],
  pending: ["◌ detonating", "held while a decoy victim follows the email in a sandbox."],
  error: ["? inconclusive", "the sandbox run didn't finish, so it's held for review instead of guessed."],
};

function renderVerdict() {
  const m = messages.find((x) => x.id === selectedMsg);
  if (!m) return verdictEl.replaceChildren();
  const [head, note] = _VERDICT[m.verdict] || _VERDICT.error;
  verdictEl.replaceChildren(h("div", { class: `verdict ${msgClass(m)}` },
    h("div", { class: "vh" }, h("span", {}, `${head} · ${m.subject || "(no subject)"}`),
      m.vector ? h("span", {}, m.vector.replace(/_/g, " ")) : null),
    m.reason ? h("p", {}, m.reason) : null,
    h("p", {}, note)));
}

// Clicking a row selects both the email and the sandbox run that judged it.
function open({ m, e }) {
  selectedMsg = m ? m.id : null;
  if (e) return select(e.id, true);
  selected = null; detailSig = "";
  panelEl.hidden = true;
  renderInbox();
  renderVerdict();
}

async function refresh() {
  const [msgRes, engRes] = await Promise.all([api("/messages"), api("/engagements")]);
  messages = msgRes.messages; engagements = engRes.engagements;
  countEl.textContent = `${engagements.length} engagement${engagements.length === 1 ? "" : "s"}`;
  renderInbox();
  renderVerdict();
  if (selected) await renderDetail(selected).catch(() => {});
}

async function select(id, scroll = true) {
  const changed = selected !== id;
  selected = id;
  const m = messages.find((x) => x.engagement_id === id);
  if (m) selectedMsg = m.id;
  if (changed) { detailSig = ""; frame = null; inspect = null; story = null; }
  await refresh();
  if (changed) {
    panelEl.classList.remove("enter"); void panelEl.offsetWidth; panelEl.classList.add("enter");
    if (scroll) setTimeout(() => verdictEl.scrollIntoView({ behavior: "smooth", block: "start" }), 120);
  }
}

function kv(label, value, mono) {
  return [h("dt", {}, label), h("dd", { class: mono ? "mono" : "" }, value ?? "—")];
}

async function renderDetail(id) {
  const d = await api(`/engagements/${id}`);
  if (id !== selected) return;
  const sig = `${id}:${d.events.length}:${(d.shots || []).length}:${d.engagement.risk_score}:${d.emails.length}:${frame}:${inspect}:${story}`;
  if (sig === detailSig) return;
  detailSig = sig;
  const eng = d.engagement;
  const persona = (d.events.find((e) => e.type === "persona.created") || {}).data || {};
  const ind = d.indicators || { indicators: [], risk_score: 0 };
  const card = (title, ...body) => h("div", { class: "card" },
    h("h3", { style: "font-size:13px;margin-bottom:12px" }, title), ...body);

  const personaCard = card("Decoy persona",
    h("dl", { class: "kv" },
      ...kv("Name", persona.name),
      ...kv("Login", persona.username, true),
      ...kv("Email", persona.email, true),
      ...kv("Customer id", persona.customer_id, true),
      ...kv("Accounts", (persona.accounts || []).join(", "), true)));

  const indCard = card(`Indicators — risk ${ind.risk_score}/100`,
    ind.indicators.length
      ? h("div", { class: "bars" }, ...ind.indicators.map((i) =>
          h("div", { class: "bar" },
            h("span", {}, i.label), h("span", { class: "mono" }, "+" + i.weight),
            h("div", { class: "track" }, h("div", { class: "fill", style: `width:${Math.min(100, i.weight * 4)}%` })))))
      : h("p", { class: "muted tiny" }, "No fraud indicators yet."));

  const timeline = card(`Timeline · ${d.events.length} events`,
    h("div", { class: "tl-wrap" }, h("ul", { class: "tl" }, ...[...d.events].reverse().map((ev) =>
      h("li", {},
        h("span", { class: "t" }, fmtTime(ev.created_at)),
        h("span", { class: "src" }, ev.source),
        h("span", {}, ev.type + eventDetail(ev)))))));

  const emails = d.emails.length ? card("Messages",
    ...d.emails.map((m) => h("div", { style: "border-bottom:1px solid var(--line-2);padding:8px 0" },
      h("div", { class: "tiny muted" }, `${m.direction === "in" ? "⬇" : "⬆"} ${m.kind} · ${m.sender || ""} → ${m.recipient || ""}`),
      h("div", { style: "font-weight:600;font-size:13px" }, m.subject || ""),
      h("div", { class: "tiny", style: "white-space:pre-wrap;color:var(--muted)" }, (m.body || "").slice(0, 400))))) : null;

  const moved = d.events.reduce((n, e) => n + (e.type === "transfer.created" ? (e.data?.amount_cents || 0) : 0), 0);
  const deposits = d.events.filter((e) => e.type === "deposit.created").length;
  const steps = d.events.filter((e) => e.type === "agent.step").length;
  const stat = (k, v) => h("div", { class: "stat" }, h("div", { class: "k" }, k), h("div", { class: "v" }, v));
  const r = eng.risk_score || 0;
  const gauge = h("div", { class: "gauge", style: `--v:${r};--gc:${r >= 60 ? "var(--red)" : r >= 30 ? "var(--amber)" : "var(--grn)"}` },
    h("div", {}, h("div", {}, h("b", { class: riskClass(r) }, String(r)), h("br"), h("span", {}, "risk"))));

  const term = panelEl.querySelector(".sb-term");
  const pinned = !term || term.scrollHeight - term.scrollTop - term.clientHeight < 30;
  panelEl.hidden = false;
  panelEl.replaceChildren(h("div", { class: "panel" },
    h("div", { class: "d-head" },
      h("div", { class: "d-title" },
        h("span", { class: "alert-kicker" }, `engagement ${eng.status}`),
        h("h2", {}, eng.subject || "Engagement"),
        h("div", { class: "tiny muted" }, (eng.scammer_email || "—") + (eng.summary ? " · " + eng.summary : "")),
        h("div", { class: "pills" }, h("span", { class: "pill" }, eng.status), ...(eng.tags || []).map((t) => h("span", { class: "pill danger" }, t.replace(/_/g, " "))))),
      gauge,
      h("button", { class: "btn btn-ghost", onClick: () => window.scrollTo({ top: 0, behavior: "smooth" }) }, "↑ inbox")),
    h("div", { class: "stats" },
      stat("moved to mule", money(moved / 100)), stat("decoy deposits", String(deposits)),
      stat("agent steps", String(steps)), stat("frames", String((d.shots || []).length))),
    buildStory(d),
    buildSandbox(d),
    h("div", { class: "d-grid" }, personaCard, indCard, timeline),
    emails));

  const t2 = panelEl.querySelector(".sb-term");
  if (t2) t2.scrollTop = pinned ? t2.scrollHeight : term.scrollTop;  // follow the newest line unless the user scrolled up
}

// --- Daytona sandbox viewer: watch the agent work inside the container -------

function buildSandbox(d) {
  const ev = d.events || [];
  const shots = d.shots || [];
  const has = ev.some((e) => ["persona.funding", "sandbox.launching", "agent.started", "agent.step"].includes(e.type));
  if (!has && !shots.length) return null;

  const finished = ev.some((e) => ["sandbox.finished", "agent.finished", "agent.error"].includes(e.type));
  const error = sandboxError(ev);
  const running = !finished;
  const local = ev.some((e) => e.type === "runtime.local");
  const sid = local ? "local chromium"
    : "daytona ◦ " + ((ev.find((e) => e.type === "sandbox.created")?.data?.sandbox_id)
      || "sbx-" + (d.engagement?.id || "").slice(0, 8));
  const target = ev.find((e) => e.type === "portal.detected")?.data?.url
    || ev.find((e) => e.type === "sandbox.launching")?.data?.bank || "";
  const lastStep = [...ev].reverse().find((e) => e.type === "agent.step");
  const url = (lastStep?.data?.url) || target || "about:blank";
  const idx = frame != null && shots[frame] ? frame : shots.length - 1;
  const shot = shots[idx];

  const lines = termLines(ev);
  if (error && !ev.some((e) => e.type === "agent.error")) lines.push({ t: "", text: "✗ " + error, cls: "err" });
  const term = h("div", { class: "sb-term" },
    h("div", { class: "ln dim" }, h("span", { class: "lt" }, ""), local ? "host runtime · headless chromium" : "daytona cloud · ephemeral sandbox"),
    ...lines.map((l) => h("div", {
      class: `ln ${l.cls || ""} ${l.ev ? "click" : ""} ${l.ev && l.ev.id === inspect ? "on" : ""}`,
      title: l.ev ? "inspect this step" : null,
      onClick: l.ev ? () => openInspect(l.ev, shots) : null,
    }, h("span", { class: "lt" }, l.t), l.text)),
    running ? h("div", { class: "ln cur" }, h("span", { class: "lt" }, ""), h("span", { class: "blink" }, "▋")) : null);

  let screen;
  if (shot) {
    screen = h("img", { class: "sb-screen", src: shot.image, alt: shot.label || "" });
  } else if (finished) {
    screen = h("div", { class: "sb-fail" }, h("b", {}, "✗ no browser frames captured"),
      h("p", {}, error || "the sandbox exited before the agent opened a page."),
      h("p", {}, "target: " + shortUrl(target)));
  } else {
    const has = (t) => ev.some((e) => e.type === t);
    const stages = local ? [
      ["daytona egress blocked → host runtime", true],
      ["launching chromium on host", has("runtime.local")],
    ] : [
      ["waiting for decoy deposits to post", has("persona.funding")],
      ["provisioning daytona sandbox", has("sandbox.launching")],
      ["checking route to the bank", has("sandbox.created")],
      ["installing playwright + chromium", has("sandbox.installing")],
      ["launching agent browser", has("agent.started")],
      ["loading " + shortUrl(target), has("agent.step")],
    ];
    const now = stages.findIndex(([, done], i) => done && !(stages[i + 1] || [])[1]);
    screen = h("div", { class: "sb-boot" }, h("span", { class: "spin" }),
      h("ul", { class: "stages" }, ...stages.map(([label, done], i) =>
        h("li", { class: i === now ? "now" : done ? "done" : "" }, label))));
  }

  const frames = shots.length > 1 ? h("div", { class: "frames" }, ...shots.map((sh, i) =>
    h("button", { class: i === idx ? "on" : "", title: sh.label || `frame ${i + 1}`,
      onClick: () => { frame = i === shots.length - 1 ? null : i; detailSig = ""; renderDetail(selected).catch(() => {}); } },
      h("img", { src: sh.image, alt: "" })))) : null;

  const view = h("div", { class: "sb-view" },
    h("div", { class: "sb-chrome" },
      h("span", { class: "c-dots" }, h("i"), h("i"), h("i")),
      h("span", { class: "c-url" }, shortUrl(url)),
      shot ? h("span", { class: "tiny muted" }, `${idx + 1}/${shots.length}${frame == null && running ? " · live" : ""}`) : null),
    screen, frames);

  return h("div", { class: `sandbox ${running ? "run" : error ? "err" : "done"}` },
    h("div", { class: "sb-bar" },
      h("span", { class: "c-dots" }, h("i"), h("i"), h("i")),
      h("span", { class: "sb-title" }, sid),
      h("span", { class: "sb-state" },
        running ? [h("span", { class: "sb-load" }), "running"] : error ? "✗ error" : "○ terminated")),
    h("div", { class: "sb-body" }, term, view),
    buildInspector(ev, shots));
}

// --- run story: email in → classified → sandbox → OTP email → money out --------

function buildStory(d) {
  const ev = d.events || [];
  // A re-judged run has more than one verdict event; the newest one is the verdict.
  const find = (t) => (t === "verdict" ? [...ev].reverse().find((e) => e.type === t) : ev.find((e) => e.type === t));
  const scamMail = (d.emails || []).find((m) => m.direction === "in");
  const otpMail = (d.emails || []).find((m) => m.kind === "otp");
  const plan = find("email.extracted")?.data || {};
  const verdict = find("verdict")?.data || {};
  const local = !!find("runtime.local");
  const transfers = ev.filter((e) => e.type === "transfer.created");
  const moved = transfers.reduce((n, e) => n + (e.data?.amount_cents || 0), 0);
  const finished = !!(find("agent.finished") || find("sandbox.finished"));
  const sbx = find("sandbox.created")?.data?.sandbox_id;

  const stages = [
    { key: "mail", icon: "✉", title: "Email held", sub: scamMail ? scamMail.sender : "waiting…",
      at: scamMail?.created_at, done: !!scamMail },
    { key: "vet", icon: "⚑", title: "Instructions read", sub: plan.asks ? `${plan.asks.length} step${plan.asks.length === 1 ? "" : "s"} to follow` : "—",
      at: find("email.extracted")?.created_at, done: !!plan.asks },
    { key: "sandbox", icon: "▣", title: local ? "Agent launched (host)" : "Sandbox spun up",
      sub: local ? "daytona egress blocked → local chromium" : sbx ? "daytona " + sbx.slice(0, 8) : "provisioning…",
      at: (find("sandbox.created") || find("sandbox.launching"))?.created_at, done: !!find("agent.started"), ev: find("agent.started") || find("sandbox.launching") },
    { key: "otp", icon: "#", title: "OTP email to decoy", sub: otpMail ? `code ${(otpMail.body.match(/\b\d{6}\b/) || [""])[0]}` : "—",
      at: otpMail?.created_at, done: !!otpMail, ev: find("agent.otp_relayed") || find("otp.sent") },
    { key: "drain", icon: verdict.verdict === "scam" ? "⚠" : "✓", title: verdict.verdict ? `Verdict: ${verdict.verdict === "error" ? "inconclusive" : verdict.verdict}` : "Outcome",
      sub: verdict.verdict ? (verdict.evidence?.length ? verdict.evidence.map((x) => x.kind.replace(/_/g, " ")).join(" · ") : verdict.verdict === "safe" ? "nothing lost" : "no result")
        : transfers.length ? `${money(moved / 100)} moving…` : finished ? "settling…" : "—",
      at: find("verdict")?.created_at, done: !!verdict.verdict, ev: find("verdict") },
  ];
  const reached = stages.filter((st) => st.done || st.at).length;
  const live = Math.max(0, reached - 1);
  const openKey = story || stages[live].key;

  const strip = h("div", { class: "story-strip" }, ...stages.map((st, i) => h("button", {
    class: `stage ${st.done ? "done" : st.at ? "now" : ""} ${st.key === openKey ? "open" : ""}`,
    onClick: () => {
      story = st.key;
      if (st.ev) { inspect = st.ev.id; frame = frameFor(st.ev, d.shots || []); }
      detailSig = ""; renderDetail(selected).catch(() => {});
    } },
    h("span", { class: "st-n" }, st.done ? "✓" : String(i + 1)),
    h("span", { class: "st-txt" }, h("b", {}, st.title), h("span", {}, st.sub)),
    h("span", { class: "st-t" }, st.at ? fmtTime(st.at) : ""))));

  let detail = null;
  if (openKey === "mail" && scamMail) detail = mailView(scamMail, "Held by scamtracker", "scam");
  else if (openKey === "vet") detail = h("div", { class: "story-note" },
    h("b", {}, "What the email asks the reader to do"), plan.summary ? h("p", {}, plan.summary) : null,
    plan.asks?.length ? h("ol", {}, ...plan.asks.map((a) => h("li", {}, a))) : h("p", {}, "—"),
    h("p", { class: "muted tiny" }, `link → ${find("portal.detected")?.data?.url || "none"} · a decoy customer was created and funded to follow these steps`));
  else if (openKey === "drain" && verdict.verdict) detail = h("div", { class: "story-note" },
    h("b", {}, "Why"), h("p", {}, verdict.reason || "—"),
    verdict.evidence?.length ? h("ul", {}, ...verdict.evidence.map((x) => h("li", {}, x.detail))) : null);
  else if (openKey === "otp" && otpMail) detail = mailView(otpMail, "Delivered to the decoy's inbox (your Gmail, +tag)", "otp");
  else detail = h("div", { class: "story-note muted tiny" }, "▸ shown in the sandbox below — the terminal line and browser frame for this step are selected");
  return h("div", { class: "story" }, strip, detail);
}

// A Gmail-style rendering of a stored email. Links are shown, never made clickable.
function mailView(m, label, kind) {
  const who = (m.sender || "?").replace(/<.*>/, "").replace(/"/g, "").trim() || m.sender;
  const parts = String(m.body || "").split(/(https?:\/\/[^\s<>")]+)/g);
  return h("div", { class: `mail ${kind}` },
    h("div", { class: "mail-top" },
      h("span", { class: "mail-av" }, (who[0] || "?").toUpperCase()),
      h("div", { class: "mail-from" }, h("b", {}, who), h("span", { class: "muted tiny" }, `<${(m.sender || "").replace(/.*</, "").replace(/>.*/, "")}> → ${m.recipient || ""}`)),
      h("span", { class: `mail-tag ${kind}` }, label),
      h("span", { class: "muted tiny" }, fmtTime(m.created_at))),
    h("div", { class: "mail-subj" }, m.subject || "(no subject)"),
    h("div", { class: "mail-body" }, ...parts.map((t, i) => (i % 2 ? h("span", { class: "mail-link" }, t) : t))));
}

// --- event inspector: click a terminal line to see that moment ----------------

function openInspect(ev, shots) {
  inspect = inspect === ev.id ? null : ev.id;
  frame = inspect == null ? null : frameFor(ev, shots);
  detailSig = "";
  renderDetail(selected).catch(() => {});
}

// The screenshot showing an event: the frame an agent step produced, else the last frame taken by then.
function frameFor(ev, shots) {
  if (!shots.length) return null;
  if (ev.type === "agent.step" && ev.data?.step != null) {
    const i = shots.findIndex((s) => s.step === ev.data.step + 1);
    if (i >= 0) return i === shots.length - 1 ? null : i;
  }
  const t = Date.parse(ev.created_at) + 1500;
  let idx = -1;
  shots.forEach((s, i) => { if (Date.parse(s.created_at) <= t) idx = i; });
  if (idx < 0) idx = 0;
  return idx === shots.length - 1 ? null : idx;
}

function buildInspector(events, shots) {
  const ev = inspect != null && events.find((e) => e.id === inspect);
  if (!ev) return h("div", { class: "sb-hint" }, "▸ click any line in the terminal to inspect that step — its data, what the agent saw, and the browser frame at that moment");
  const x = ev.data || {};
  const close = h("button", { class: "btn btn-ghost", onClick: () => { inspect = null; frame = null; detailSig = ""; renderDetail(selected).catch(() => {}); } }, "● back to live");
  const sections = [];
  if (ev.type === "agent.step") {
    sections.push(h("div", { class: "insp-col" },
      h("h4", {}, "what claude saw"),
      h("div", { class: "insp-k" }, "url"), h("div", { class: "mono" }, x.url || "—"),
      h("div", { class: "insp-k" }, `fields (${(x.page_fields || []).length})`),
      h("div", { class: "chips" }, ...(x.page_fields || []).filter(Boolean).map((f) => h("span", { class: "pill" }, f))),
      h("div", { class: "insp-k" }, "buttons / links"),
      h("div", { class: "chips" }, ...(x.page_buttons || []).map((b) => h("span", { class: "pill" }, b))),
      x.page_text ? h("pre", { class: "insp-pre" }, x.page_text) : null));
    sections.push(h("div", { class: "insp-col" },
      h("h4", {}, "what claude did"),
      h("div", { class: "insp-k" }, "reasoning"), h("div", {}, x.observation || "—"),
      h("div", { class: "insp-k" }, "typed"),
      (x.fills || []).length
        ? h("table", { class: "dt" }, ...(x.fills || []).map((f) => h("tr", {}, h("td", { class: "muted" }, f.field), h("td", { class: "mono" }, f.value))))
        : h("div", { class: "muted" }, "nothing"),
      h("div", { class: "insp-k" }, "clicked"), h("div", { class: "mono" }, x.click || "—"),
      h("div", { class: "insp-k" }, "decision time"), h("div", { class: "mono" }, x.think_ms != null ? `${x.think_ms} ms` : "—"),
      h("div", { class: "insp-k" }, "done?"), h("div", { class: "mono" }, x.done ? "yes" : "no")));
  }
  sections.push(h("div", { class: "insp-col" },
    h("h4", {}, "raw event"),
    h("pre", { class: "insp-pre" }, JSON.stringify({ id: ev.id, source: ev.source, type: ev.type, at: ev.created_at, data: x }, null, 2))));
  return h("div", { class: "sb-inspect" },
    h("div", { class: "insp-head" },
      h("span", { class: "src" }, ev.source), h("b", {}, ev.type), h("span", { class: "muted tiny" }, fmtTime(ev.created_at)),
      h("span", { style: "margin-left:auto" }, close)),
    h("div", { class: "insp-body" }, ...sections));
}

// The agent's own error event, or (for runs that couldn't report back) the last error line of its output.
function sandboxError(ev) {
  const e = [...ev].reverse().find((x) => x.type === "agent.error");
  if (e) return e.data?.error || "agent error";
  const tail = ev.find((x) => x.type === "sandbox.finished")?.data?.stdout_tail || "";
  if (!/Traceback|Error/.test(tail)) return "";
  const line = tail.split("\n").reverse().find((l) => /Error|Exception/.test(l) && !l.startsWith(" "));
  return (line || "agent crashed").replace(/^[\w.]+Error: /, "").slice(0, 240);
}

const _GLYPH = { err: "✗", ok: "✓", cmd: "$", step: "▸" };
function termLines(events) {
  const out = [];
  let cur = null;
  const push = (t, text, cls) => out.push({ ev: cur, t: fmtTime(t), text: `${_GLYPH[cls] || "▸"} ${text}`, cls: cls === "err" ? "err" : cls === "ok" ? "ok" : cls === "cmd" ? "cmd" : "" });
  for (const e of events) {
    cur = e;
    const x = e.data || {}, t = e.created_at;
    switch (e.type) {
      case "persona.funding": push(t, `waiting for decoy deposits to post…`); break;
      case "persona.funded": push(t, x.balance_cents ? `decoy funded · ${money(x.balance_cents / 100)} available` : `deposits still pending — starting anyway`, x.balance_cents ? "ok" : ""); break;
      case "sandbox.launching": push(t, `daytona create --snapshot chromium`, "cmd"); break;
      case "sandbox.created": push(t, `sandbox ${x.sandbox_id || ""} ready`, "ok"); break;
      case "sandbox.installing": push(t, `installing playwright + chromium…`, "cmd"); break;
      case "sandbox.egress_blocked": push(t, `sandbox can't reach ${shortUrl(x.public_url || "")} (${x.status}) — daytona egress allowlist`, "err"); break;
      case "runtime.local": push(t, `falling back to host runtime · python bank_agent.py${x.host ? " @ " + x.host : ""}`, "cmd"); break;
      case "agent.browser": push(t, `${x.browser || "chromium"} up · ${x.viewport || ""} · model ${x.model || ""}`); break;
      case "agent.started": push(t, `agent online → ${x.start ? shortUrl(x.start) : "reading the email"}`); break;
      case "agent.step": push(t, (x.observation || `step @ ${shortUrl(x.url || "")}`) + (x.click ? `  ⟶ click "${x.click}"` : "")); break;
      case "otp.sent": push(t, `one-time code issued to inbox`); break;
      case "agent.otp_relayed": push(t, `OTP ${x.got ? "read from inbox, entered ✓" : "requested…"}`, x.got ? "ok" : ""); break;
      case "session.login": push(t, `signed in as @${x.username || "victim"}`, "ok"); break;
      case "email.extracted": push(t, `email read · ${(x.asks || []).length} instruction(s) to follow`); break;
      case "transfer.created": push(t, `transfer ${money((x.amount_cents || 0) / 100)} → ${String(x.payee_id || "").slice(-6)}`); break;
      case "secret.disclosed": push(t, `decoy ${x.kind} handed to ${x.host || x.channel || "?"}`, "err"); break;
      case "agent.reply": push(t, `drafted a reply to ${x.to || "sender"} (not sent)`); break;
      case "ledger.reconciled": push(t, `nessie ledger read back · ${x.outflows} outflow(s) confirmed`, "cmd"); break;
      case "verdict": push(t, `verdict: ${x.verdict === "error" ? "inconclusive" : x.verdict.toUpperCase()}`, x.verdict === "scam" ? "err" : "ok"); break;
      case "scammer.drain": case "engagement.drained": push(t, `account drained · ${money((x.moved_cents || 0) / 100)} moved`, "ok"); break;
      case "agent.finished": push(t, x.summary ? `done — ${x.summary}` : `sequence complete`, "ok"); break;
      case "sandbox.finished": push(t, events.some((x) => x.type === "runtime.local") ? `agent process exited` : `daytona sandbox delete`, "cmd"); break;
      case "agent.error": push(t, x.error || "agent error", "err"); break;
      default: break;
    }
  }
  return out;
}

function shortUrl(u) {
  if (!u) return "about:blank";
  return u.replace(/^https?:\/\//, "").replace(/\/$/, "").slice(0, 46);
}

function eventDetail(ev) {
  const d = ev.data || {};
  if (d.amount_cents != null) return ` — ${money(d.amount_cents / 100)}${d.payee_id ? " → " + String(d.payee_id).slice(-6) : ""}`;
  if (d.moved_cents != null) return ` — ${money(d.moved_cents / 100)} total`;
  if (d.vector) return ` — ${d.vector}`;
  if (d.username) return ` — @${d.username}`;
  return "";
}

document.getElementById("refresh").addEventListener("click", () => refresh().catch(console.error));
document.getElementById("sim").addEventListener("click", async (e) => {
  e.target.disabled = true;
  try {
    const res = await api("/sim/run-full", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    if (res.engagement_id) setTimeout(() => select(res.engagement_id), 600);
  } catch (err) { alert(err.message); } finally { e.target.disabled = false; }
});

renderStatus();
refresh().catch((e) => { inboxEl.replaceChildren(h("div", { class: "empty-panel" }, "Can't reach the orchestrator at /api. Is it running?")); console.error(e); });
setInterval(() => refresh().catch(() => {}), 3000);

// --- scenario swarm view -----------------------------------------------------
// Nessie generates one bank per scam type with that fraud planted; every customer is analyzed in its
// own Daytona sandbox. This view streams the swarm: a tile per sandbox, a per-scenario scoreboard, and
// the live Nessie API log.

const SCEN_DESC = {};
let swarmId = null, swarmTimer = null, swarmCase = null, lastCallId = 0;
const SCEN_COLORS = {};

function switchView(v) {
  document.querySelectorAll(".vtab").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  document.getElementById("view-monitor").hidden = v !== "monitor";
  document.getElementById("view-swarm").hidden = v !== "swarm";
  if (v === "swarm") { loadScenarios(); attachLatestSwarm(); }
}

async function attachLatestSwarm() {
  if (swarmId) return pollSwarm();
  try {
    const { runs } = await api("/swarm");
    if (runs && runs.length) { swarmId = runs[0].id; pollSwarm(); }
  } catch { /* none yet */ }
}
document.querySelectorAll(".vtab").forEach((b) => b.addEventListener("click", () => switchView(b.dataset.view)));

async function loadScenarios() {
  if (Object.keys(SCEN_DESC).length) return;
  try {
    const { scenarios } = await api("/swarm/scenarios");
    scenarios.forEach((x) => { SCEN_DESC[x.id] = x.desc; });
  } catch { /* best effort */ }
}

document.getElementById("sw-run").addEventListener("click", async (e) => {
  const body = {
    customers: +document.getElementById("sw-cust").value || 40,
    anomaly_rate: (+document.getElementById("sw-rate").value || 18) / 100,
    concurrency: +document.getElementById("sw-conc").value || 80,
    use_claude: document.getElementById("sw-claude").checked,
  };
  e.target.disabled = true; e.target.textContent = "launching…";
  try {
    const res = await api("/swarm/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    swarmId = res.run_id; swarmCase = null; lastCallId = 0;
    document.getElementById("sw-grid").replaceChildren();
    document.getElementById("sw-log").replaceChildren();
    pollSwarm();
  } catch (err) { alert(err.message); } finally { e.target.disabled = false; e.target.textContent = "launch swarm"; }
});

function pollSwarm() {
  clearTimeout(swarmTimer);
  renderSwarm().finally(() => { swarmTimer = setTimeout(pollSwarm, 1200); });
}

const SW_SCEN_COLOR = (sc) => sc === "clean" ? "var(--txt-faint)" : "var(--grn-dim)";

async function renderSwarm() {
  if (!swarmId || document.getElementById("view-swarm").hidden) return;
  let d;
  try { d = await api(`/swarm/${swarmId}`); } catch { return; }
  const t = d.run.totals || {};
  const cases = d.cases || [];
  renderSwarmStats(d.run, t, cases);
  renderSwarmGrid(cases);
  renderSwarmScore(t);
  renderNessieLog();
  if (d.run.status === "finished" || d.run.status === "error") clearTimeout(swarmTimer);
}

function renderSwarmStats(run, t, cases) {
  const live = cases.filter((c) => c.status === "booting" || c.status === "analyzing").length;
  const done = cases.filter((c) => c.status === "done").length;
  const base = t.per_scenario?.baseline || {};
  const stat = (k, v, sub) => h("div", { class: "stat" }, h("div", { class: "k" }, k),
    h("div", { class: "v" }, v), sub ? h("div", { class: "tiny muted" }, sub) : null);
  document.getElementById("sw-stats").replaceChildren(
    stat("sandboxes live", String(live), run.status),
    stat("cases analyzed", `${done}/${cases.length}`, `${run.customers}/type · ${Math.round(run.anomaly_rate * 100)}% fraud`),
    stat("Nessie calls", String(t.nessie_calls || 0), `${t.nessie_ms || 0}ms avg`),
    stat("flagged", String(t.flagged || 0), `${base.flagged || 0} on baseline traffic`));
}

function renderSwarmGrid(cases) {
  const g = document.getElementById("sw-grid");
  const cur = g.children.length;
  const legend = document.getElementById("sw-legend");
  if (!legend.children.length) legend.replaceChildren(
    ...[["booting", "#3a3a3a"], ["analyzing", "var(--amber)"], ["done", "var(--grn-dim)"], ["baseline (default mix)", "#2b2b2b"], ["error", "var(--red-dim)"]]
      .map(([t, c]) => h("span", {}, h("i", { style: `background:${c}` }), t)));
  cases.forEach((c, i) => {
    let cell = g.children[i];
    if (!cell) { cell = h("div", { class: "cell", onClick: () => openCase(c) }); g.appendChild(cell); }
    cell.className = `cell ${c.scenario === "baseline" ? "base " : ""}${c.status}${swarmCase === c.id ? " sel" : ""}`;
    cell.title = `${c.scenario} · ${c.status}${c.n_txns ? ` · ${c.n_txns} txns` : ""}${c.flagged ? ` · ${c.flagged} flagged` : ""}`;
  });
}

function renderSwarmScore(t) {
  const per = t.per_scenario || {};
  const order = [...Object.keys(per).filter((k) => k !== "baseline"), "baseline"];
  const rows = order.map((sc) => {
    const p = per[sc] || {};
    const planted = p.planted || 0, flagged = p.flagged || 0;
    const pct = planted ? Math.min(100, Math.round(flagged / planted * 100)) : 0;
    const right = `${flagged}/${planted}`;
    return h("div", { class: `srow ${sc === "baseline" ? "base" : ""}` },
      h("span", { class: "sname" }, sc.replace(/_/g, " ")),
      h("div", { class: "sbar" }, h("i", { style: `width:${pct}%` })),
      h("span", { class: "snum" }, right));
  });
  const head = h("div", { class: "tiny muted", style: "margin-bottom:6px" },
    "bar = flagged ÷ planted (Nessie's injected count) per scam type");
  document.getElementById("sw-score").replaceChildren(head, ...rows);
}

async function renderNessieLog() {
  if (!swarmId) return;
  let d;
  try { d = await api(`/nessie/calls?scope=${swarmId}&limit=12`); } catch { return; }
  const el = document.getElementById("sw-log");
  el.replaceChildren(...d.calls.map((c) => h("div", { class: "lg" },
    h("b", {}, c.method + " "), h("span", { class: "mono" }, shortPath(c.path)), " ",
    h("span", { class: c.status >= 400 ? "er" : "" }, String(c.status || "…")),
    h("span", { class: "muted" }, ` · ${c.ms}ms`))));
}

function shortPath(p) { return (p || "").split("?")[0].replace(/\/(acct|cust|txn|sim)_\w+/g, (m) => m.slice(0, 9) + "…"); }

async function openCase(c) {
  swarmCase = c.id;
  renderSwarmGrid(await api(`/swarm/${swarmId}`).then((d) => d.cases).catch(() => []));
  const box = document.getElementById("sw-caseview");
  box.hidden = false;
  let full;
  try { full = (await api(`/swarm/${swarmId}/cases/${c.id}`)).case; } catch { return; }
  const r = full.result || {};
  const kv = (k, v) => h("div", { class: "srow", style: "grid-template-columns:150px 1fr" }, h("span", { class: "muted" }, k), h("span", {}, v));
  box.replaceChildren(
    h("div", { class: "eng-row", style: "margin-bottom:10px" },
      h("h3", { style: "font-size:14px" }, `case · ${full.scenario.replace(/_/g, " ")}`),
      h("button", { class: "btn btn-ghost", onClick: () => { swarmCase = null; box.hidden = true; } }, "✕")),
    kv("runtime", `${full.runtime || "—"}${full.sandbox_id ? " · " + full.sandbox_id.slice(0, 12) : ""}`),
    kv("customer", full.customer_id || "—"),
    kv("transactions", String(full.n_txns || 0)),
    kv("flagged", `${full.flagged || 0} (${r.flagged_rules || 0} by rules${r.claude_added ? ", " + r.claude_added + " by claude" : ""})`),
    kv("borderline → claude", String(r.borderline || 0)),
    kv("detector time", r.ms != null ? `${r.ms} ms` : "—"),
    r.samples && r.samples.length ? h("div", { style: "margin-top:10px" },
      h("div", { class: "tiny muted", style: "margin-bottom:6px" }, "flagged transactions"),
      h("table", { class: "dt" },
        h("tr", {}, h("th", {}, "by"), h("th", {}, "why")),
        ...r.samples.map((x) => h("tr", {}, h("td", {}, x.by), h("td", {}, (x.why || []).join(", ")))))) : null);
}
