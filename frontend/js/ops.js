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
      h("span", { class: `vtag ${m?.grade || ""}` }, verdict === "pending" ? "running" : verdict === "error" ? "review"
        : verdict === "scam" && m?.grade ? `scam·${m.grade}` : verdict),
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
  scam: ["⚠ scam · likely", "quarantined. Following the email in the sandbox cost the decoy victim. The decoy stays ARMED: if the scammer comes back and uses the phished credentials, this becomes confirmed."],
  confirmed: ["⚠ scam · confirmed", "quarantined. The phished credentials were used by a third party (or the money went to a mule we'd already seen). Proof from outside the sandbox, not inference."],
  safe: ["✓ safe", "delivered. The decoy victim followed the email in the sandbox and lost nothing."],
  pending: ["◌ detonating", "held while a decoy victim follows the email in a sandbox."],
  error: ["? inconclusive", "the sandbox run didn't finish, so it's held for review instead of guessed."],
};

function renderVerdict() {
  const m = messages.find((x) => x.id === selectedMsg);
  if (!m) return verdictEl.replaceChildren();
  const [head, note] = (m.verdict === "scam" && m.grade === "confirmed" ? _VERDICT.confirmed : _VERDICT[m.verdict]) || _VERDICT.error;
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
  renderWatchlist().catch(() => {});
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
  const sig = `${id}:${d.events.length}:${(d.shots || []).length}:${d.engagement.risk_score}:${d.emails.length}:${frame}:${inspect}:${story}:${d.engagement.status}:${d.decoy?.otp}:${(d.interdictions || []).length}:${(d.related?.others || []).length}`;
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
    buildArmed(d),
    buildPlaybook(d),
    h("div", { class: "d-grid" }, personaCard, indCard, timeline),
    buildFlow(d),
    emails));

  const t2 = panelEl.querySelector(".sb-term");
  if (t2) t2.scrollTop = pinned ? t2.scrollHeight : term.scrollTop;  // follow the newest line unless the user scrolled up
}

// --- armed: the decoy stays live, waiting for the scammer to come back ------------

const cardH = (title, ...body) => h("div", { class: "card" }, h("h3", { style: "font-size:13px;margin-bottom:12px" }, title), ...body);
const short = (id) => String(id || "").slice(-6);

function buildArmed(d) {
  const eng = d.engagement, dec = d.decoy;
  if (!dec || !["armed", "confirmed"].includes(eng.status)) return null;
  const confirmed = eng.status === "confirmed";
  const intruders = (d.playbook?.sessions || []).filter((s) => s.actor === "external");
  const launderBtn = h("button", { class: "btn btn-light", onClick: async (e) => {
    e.target.disabled = true; e.target.textContent = "laundering…";
    try { await api(`/sim/launder/${eng.id}`, { method: "POST" }); e.target.textContent = "laundering · watch the terminal"; detailSig = ""; await renderDetail(eng.id); return; }
    catch (err) { alert(err.message); } finally { e.target.disabled = false; e.target.textContent = "./simulate --launder"; }
  } }, "./simulate --launder");
  return h("div", { class: `armed ${confirmed ? "confirmed" : ""}` },
    h("div", { class: "armed-head" },
      h("span", { class: "armed-dot" }),
      h("b", {}, confirmed ? "CONFIRMED · a third party used the phished credentials" : "ARMED · waiting for the scammer to come back"),
      h("span", { class: "muted tiny" }, confirmed
        ? `${intruders.length} intruder session(s) · the account stays live to keep collecting`
        : "the decoy account stays live; any sign-in that isn't our agent's is the proof")),
    h("div", { class: "armed-grid" },
      h("div", {},
        h("div", { class: "insp-k" }, "the phished credentials (what the scammer holds)"),
        h("dl", { class: "kv" }, ...kv("Bank", dec.bank_url, true), ...kv("User ID", dec.username, true),
          ...kv("Password", dec.password, true), ...kv("Latest OTP", dec.otp || "— (issued on sign-in; shows here)", true)),
        h("p", { class: "muted tiny" }, "Play the returning scammer: open the bank in another browser or your phone, sign in with these, read the code here. In production this waits hours or days.")),
      h("div", {},
        h("div", { class: "insp-k" }, "intruder sessions"),
        intruders.length ? h("table", { class: "dt" }, ...intruders.map((s) => h("tr", {},
          h("td", { class: "mono" }, s.sid), h("td", {}, fmtTime(s.login_at || s.opened_at)), h("td", { class: "mono" }, s.ip || "?"),
          h("td", {}, s.ua_family), h("td", {}, `${s.money.filter((m) => m.status === "accepted").length} moves · ${s.declines.length} refused`))))
          : h("p", { class: "muted tiny" }, "none yet"),
        h("div", { class: "insp-k", style: "margin-top:10px" }, "downstream"),
        h("div", { class: "controls" }, launderBtn,
          h("span", { class: "muted tiny" }, "the mule fans the money out to a fresh layer and cashes out — simulated, on real Nessie transactions")))));
}

// --- playbook: how the attacker operated --------------------------------------------

function buildPlaybook(d) {
  const pb = d.playbook;
  if (!pb || !pb.subject) return null;
  const m = pb.metrics || {};
  const s = (v, unit = "") => (v == null ? "—" : `${v}${unit}`);
  const stat = (k, v, sub) => h("div", { class: "stat" }, h("div", { class: "k" }, k), h("div", { class: "v" }, v), sub ? h("div", { class: "tiny muted" }, sub) : null);
  const who = pb.third_party ? "the intruder" : "the decoy agent";
  return h("div", { class: "card pb" },
    h("div", { class: "eng-row" },
      h("h3", { style: "font-size:13px" }, `Playbook · ${who} · session ${pb.subject}`),
      pb.profile ? h("span", { class: `pill ${pb.third_party ? "danger" : ""}`, title: pb.profile.why }, pb.profile.label) : null),
    h("p", { class: "tiny muted", style: "margin:4px 0 12px" }, pb.summary + (pb.profile ? ` · read: ${pb.profile.why}.` : "")),
    h("div", { class: "pb-stages" }, ...pb.stages.map((st) => h("div", { class: `pb-stage ${st.done ? "done" : ""}` },
      h("div", { class: "pb-title" }, h("span", { class: "pb-n" }, st.done ? "●" : "○"), st.title, st.at ? h("span", { class: "muted tiny" }, fmtTime(st.at)) : null),
      ...st.lines.map((l) => h("div", { class: "pb-line" }, l))))),
    h("div", { class: "stats pb-stats" },
      stat("login → first move", s(m.secs_login_to_first_move, "s"), m.secs_login_to_first_move != null && m.secs_login_to_first_move < 15 ? "scripted-fast" : "human pace"),
      stat("recon reads", s(m.recon_reads), "before touching money"),
      stat("refused by limit", s(m.declined_attempts), `limit ${money((m.limit_cents || 0) / 100)}`),
      stat("structured", m.structured ? "yes" : "no", m.internal_sweeps ? `${m.internal_sweeps} internal sweep(s)` : "no sweep"),
      stat("lockout", m.lockout ? (m.lockout_first ? "first" : "after") : "no", "contact details changed"),
      stat("fingerprint", pb.fingerprint?.hash || "—", `${pb.fingerprint?.ops || ""} · ${pb.fingerprint?.ua_family || ""}`)),
    d.related?.others?.length ? h("div", { class: "pb-related" },
      h("b", {}, `Crew ${d.related.crew}: `), `linked to ${d.related.others.length} other engagement(s) by ${d.related.why.join(", ")} — `,
      ...d.related.others.map((o) => h("a", { href: "#", onClick: (e) => { e.preventDefault(); select(o); } }, o.slice(0, 8) + " "))) : null);
}

// --- money flow: follow it past the mule -------------------------------------------

const _flowCache = {};
function buildFlow(d) {
  const eng = d.engagement;
  const outflows = d.events.filter((e) => e.type === "transfer.created").length + d.events.filter((e) => e.type === "mule.network").length;
  if (!outflows) return null;
  const box = h("div", { class: "card" }, h("h3", { style: "font-size:13px;margin-bottom:6px" }, "Money flow · decoy → mule → layer → cash"),
    h("p", { class: "tiny muted", style: "margin:0 0 10px" }, "Read live from Nessie. Past the mule, this is only visible because the whole sandbox is one bank — the view a consortium would have."));
  const key = `${eng.id}:${outflows}`;
  const draw = (f) => box.append(flowSvg(f));
  if (_flowCache[key]) draw(_flowCache[key]);
  else api(`/engagements/${eng.id}/flow`).then((f) => { _flowCache[key] = f; draw(f); }).catch(() => box.append(h("p", { class: "muted tiny" }, "flow unavailable")));
  return box;
}

const NS = "http://www.w3.org/2000/svg";
function sv(tag, attrs, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  for (const k of kids) el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return el;
}

function flowSvg(f) {
  const cols = { decoy: 0, mule: 1, layer: 2, cash: 3 };
  const byCol = {};
  for (const n of f.nodes) (byCol[cols[n.role] ?? 1] ||= []).push(n);
  const W = 860, colW = 210, rowH = 54, pad = 20;
  const rows = Math.max(1, ...Object.values(byCol).map((a) => a.length));
  const H = pad * 2 + rows * rowH;
  const pos = {};
  for (const [c, list] of Object.entries(byCol)) list.forEach((n, i) => { pos[n.id] = { x: pad + c * colW + 70, y: pad + 20 + i * rowH + (rows - list.length) * rowH / 2 }; });
  const color = { decoy: "var(--grn)", mule: "var(--red)", layer: "var(--amber)", cash: "var(--txt-dim)" };
  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, class: "flow" });
  for (const e of f.edges) {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) continue;
    const mid = (a.x + b.x) / 2;
    svg.append(sv("path", { d: `M${a.x + 60},${a.y} C${mid},${a.y} ${mid},${b.y} ${b.x - 60},${b.y}`,
      class: `fe ${e.status || ""} ${e.by || ""}` }));
    svg.append(sv("text", { x: mid, y: (a.y + b.y) / 2 - 6, class: "fl" }, `${money((e.amount_cents || 0) / 100)}${e.by ? " · " + (e.by === "agent" ? "agent" : "intruder") : ""}${e.status === "declined" ? " ✗" : ""}`));
  }
  for (const n of f.nodes) {
    const p = pos[n.id];
    if (!p) continue;
    const g = sv("g", { transform: `translate(${p.x - 60},${p.y - 18})` });
    g.append(sv("rect", { width: 120, height: 36, rx: 7, class: `fn ${n.role} ${n.watchlisted ? "wl" : ""}`, style: `stroke:${color[n.role] || "#888"}` }));
    g.append(sv("text", { x: 60, y: 15, class: "fnt" }, n.role === "cash" ? "cash out" : `${n.role} · ${short(n.id)}`));
    g.append(sv("text", { x: 60, y: 29, class: "fns" }, n.role === "cash" ? "" : `${n.type || ""} ${n.balance_cents != null ? money(n.balance_cents / 100) : ""}${n.watchlisted ? " · watchlisted" : ""}`));
    svg.append(g);
  }
  return svg;
}

// --- bank-wide watchlist pane -----------------------------------------------------

let wlSig = "";
async function renderWatchlist() {
  const el = document.getElementById("wl-body");
  if (!el) return;
  let d;
  try { d = await api("/intel/watchlist"); } catch { return; }
  const sig = JSON.stringify([d.watchlist.map((w) => w.account_id + w.grade), d.interdictions.map((i) => i.id), d.screening]);
  if (sig === wlSig) return;
  wlSig = sig;
  document.getElementById("wl-mode").textContent = `screening: ${d.screening === "decision_hook" ? "nessie decision hook (declined before it settles)" : d.screening === "poller" ? "event poller (cancelled in the pending window)" : "off"}`;
  const wl = d.watchlist.length ? h("table", { class: "dt" },
    h("tr", {}, h("th", {}, "account"), h("th", {}, "role"), h("th", {}, "grade"), h("th", {}, "from engagement"), h("th", {}, "received")),
    ...d.watchlist.map((w) => h("tr", {}, h("td", { class: "mono" }, short(w.account_id)), h("td", {}, w.role),
      h("td", {}, h("span", { class: `pill ${w.grade === "confirmed" ? "danger" : ""}` }, w.grade)),
      h("td", {}, h("a", { href: "#", onClick: (e) => { e.preventDefault(); select(w.engagement_id); } }, w.engagement_id.slice(0, 8))),
      h("td", {}, money((w.received_cents || 0) / 100)))))
    : h("p", { class: "muted tiny" }, "empty — run a scam through and its mule lands here");
  const hits = d.interdictions.length ? h("table", { class: "dt" },
    h("tr", {}, h("th", {}, "when"), h("th", {}, "customer → payee"), h("th", {}, "amount"), h("th", {}, "action"), h("th", {}, "why")),
    ...d.interdictions.map((i) => h("tr", { class: "hit" }, h("td", {}, fmtTime(i.created_at)),
      h("td", { class: "mono" }, `${short(i.payer_id)} → ${short(i.payee_id)}`), h("td", {}, money((i.amount_cents || 0) / 100)),
      h("td", {}, h("span", { class: "pill danger" }, i.action)), h("td", { class: "tiny muted" }, i.reason || ""))))
    : h("p", { class: "muted tiny" }, "no customer has tried to pay a watchlisted account yet");
  el.replaceChildren(h("div", { class: "wl-cols" },
    h("div", {}, h("div", { class: "insp-k" }, `mule watchlist · ${d.watchlist.length}`), wl),
    h("div", {}, h("div", { class: "insp-k" }, `interdictions · ${d.interdictions.length}`), hits)));
}

document.getElementById("sim-pay")?.addEventListener("click", async (e) => {
  const out = document.getElementById("wl-result");
  e.target.disabled = true; e.target.textContent = "customer paying…";
  out.textContent = "an ordinary customer is sending money to the most recent mule…";
  try {
    const r = await api("/sim/customer-pays-mule", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    const act = r.interdiction?.action || r.status;
    out.replaceChildren(h("span", { class: act === "declined" || act === "cancelled" ? "ok" : "er" },
      `${r.customer?.name} → ${short(r.mule)} · ${money((r.amount_cents || 0) / 100)} · ${act.toUpperCase()}`),
      h("span", { class: "muted" }, r.interdiction ? ` — ${r.interdiction.reason}` : r.decision_reason ? ` — ${r.decision_reason}` : r.error ? ` — ${r.error}` : " — still pending; the feed screens it within seconds"));
    wlSig = ""; renderWatchlist();
  } catch (err) { out.textContent = err.message; }
  finally { e.target.disabled = false; e.target.textContent = "./simulate --customer-pays-mule"; }
});

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
      case "otp.sent": push(t, x.actor && x.actor !== "agent" ? `⚠ one-time code requested by a THIRD PARTY (${x.ip || "?"}) — sent to the decoy's inbox` : `one-time code issued to inbox`, x.actor && x.actor !== "agent" ? "err" : ""); break;
      case "agent.otp_relayed": push(t, `OTP ${x.got ? "read from inbox, entered ✓" : "requested…"}`, x.got ? "ok" : ""); break;
      case "login.password_ok": push(t, x.actor === "agent" ? `password accepted (decoy agent)` : `⚠ password accepted from OUTSIDE · ${x.ip || "?"} · ${(x.ua || "").slice(0, 40)}`, x.actor === "agent" ? "" : "err"); break;
      case "login.failed": push(t, `wrong password tried from ${x.ip || "?"}`, "err"); break;
      case "session.login": push(t, x.actor === "agent" ? `signed in (decoy agent · ${x.sid || ""})` : `⚠ THIRD PARTY signed in · ${x.sid || ""} · ${x.ip || "?"}`, x.actor === "agent" ? "ok" : "err"); break;
      case "credential.used_by_third_party": push(t, `CANARY · phished credentials used by a third party (${x.stage}) — scam CONFIRMED`, "err"); break;
      case "transfer.declined": push(t, `${x.actor === "agent" ? "agent" : "intruder"} tried ${money((x.amount_cents || 0) / 100)} → refused (limit ${money((x.limit_cents || 0) / 100)})`, "err"); break;
      case "money.attempt": push(t, `${x.actor === "agent" ? "agent" : "intruder"} ${x.kind} ${money((x.amount_cents || 0) / 100)}${x.payee_id ? " → " + String(x.payee_id).slice(-6) : ""} · ${x.status}${x.reason ? " (" + x.reason + ")" : ""}`, x.status === "accepted" ? "" : "err"); break;
      case "contact.changed": push(t, `${x.actor === "agent" ? "agent" : "intruder"} changed ${(x.fields || []).join(", ")}${x.changes?.email ? " → " + x.changes.email.to : ""} — lockout`, "err"); break;
      case "watchlist.hit": push(t, `WATCHLIST · customer ${String(x.payer_id || "").slice(-6)} → ${x.role} ${String(x.payee_id || "").slice(-6)} · ${money((x.amount_cents || 0) / 100)} ${x.action} (${x.source})`, "ok"); break;
      case "watchlist.match": push(t, `payee ${String(x.payee_id || "").slice(-6)} is a known mule from engagement ${x.engagement_id} — CONFIRMED`, "err"); break;
      case "mule.cashout": push(t, x.error ? `cash-out from layer ${short(x.account)} failed: ${x.error}` : `layer ${short(x.account)} cashed out ${money((x.amount_cents || 0) / 100)} at an ATM (simulated)`, x.error ? "err" : "ok"); break;
      case "mule.launder_error": push(t, `launder simulation failed: ${x.error}`, "err"); break;
      case "mule.network": push(t, `mule ${String(x.mule || "").slice(-6)} laundered → ${(x.layers || []).length} layer accounts${x.cashout?.amount_cents ? ", " + money(x.cashout.amount_cents / 100) + " cashed out" : ""} (simulated downstream)`, "cmd"); break;
      case "email.extracted": push(t, `email read · ${(x.asks || []).length} instruction(s) to follow`); break;
      case "transfer.created": push(t, `transfer ${money((x.amount_cents || 0) / 100)} → ${String(x.payee_id || "").slice(-6)}`); break;
      case "secret.disclosed": push(t, `decoy ${x.kind} handed to ${x.host || x.channel || "?"}`, "err"); break;
      case "agent.reply": push(t, `drafted a reply to ${x.to || "sender"} (not sent)`); break;
      case "ledger.reconciled": push(t, `nessie ledger read back · ${x.outflows} outflow(s) confirmed`, "cmd"); break;
      case "verdict": push(t, `verdict: ${x.verdict === "error" ? "inconclusive" : x.verdict.toUpperCase()}`, x.verdict === "scam" ? "err" : "ok"); break;
      case "scammer.drain": case "engagement.drained": push(t, `account drained · ${money((x.moved_cents || 0) / 100)} moved`, "ok"); break;
      case "agent.finished": push(t, x.summary ? `done — ${x.summary}` : `sequence complete`, "ok"); break;
      case "sandbox.finished": push(t, events.some((x) => x.type === "runtime.local") ? `agent process exited` : `daytona sandbox delete`, "cmd"); break;
      case "detonation.resumed": push(t, `orchestrator restarted — resuming this run`, "cmd"); break;
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
  document.getElementById("view-memory").hidden = v !== "memory";
  if (v === "swarm") { loadScenarios(); attachLatestSwarm(); }
  if (v === "memory") renderMemory();
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


// --- scam memory: the long-term picture across every scam ever detonated ---------------

let memData = null, memSig = "", memQ = "";
const memEl = (id) => document.getElementById(id);
const memVisible = () => !memEl("view-memory").hidden;

async function renderMemory() {
  try {
    memData = await api("/intel/memory");
  } catch (e) {
    if (!memData) memEl("mem-table").replaceChildren(h("div", { class: "mem-empty" }, `scam memory unavailable: ${e.message} (restart the orchestrator to pick up /intel/memory)`));
    return;
  }
  const sig = JSON.stringify(memData.totals) + memData.scams.map((d) => `${d.id}:${d.status}:${d.moved_out_cents}:${d.fingerprint}`).join("|") + "#" + memQ;
  if (sig === memSig) return;
  memSig = sig;
  renderMemStats(memData.totals);
  renderMemPatterns(memData);
  renderMemTable(memData);
}

function renderMemStats(t) {
  const stat = (k, v, sub, hot) => h("div", { class: `stat ${hot ? "hot" : ""}` },
    h("div", { class: "k" }, k), h("div", { class: "v" }, v), sub ? h("div", { class: "sub" }, sub) : null);
  memEl("mem-stats").replaceChildren(
    stat("scams remembered", String(t.scams), `of ${t.detonated} emails detonated · ${t.confirmed} confirmed by a third party`),
    stat("drained from decoys", money(t.moved_out_cents / 100), "money scammers took from honeypot accounts", t.moved_out_cents > 0),
    stat("mule accounts known", String(t.mules), t.repeat_mules ? `${t.repeat_mules} seen in more than one scam` : "watchlisted for the whole bank", t.repeat_mules > 0),
    stat("recurring playbooks", String(t.recurring_playbooks), "same op-sequence fingerprint, different email", t.recurring_playbooks > 0),
    stat("blocked for real customers", String(t.blocked), t.blocked ? `${money(t.blocked_cents / 100)} stopped before it settled` : "transfers to known mules declined"),
    stat("credential leaks", String(t.credential_leaks), `${t.third_party_logins} third-party sign-in(s) with phished logins`, t.third_party_logins > 0));
}

function patternCard(title, sub, groups, opts = {}) {
  const max = Math.max(1, ...groups.map((g) => g.count));
  const label = opts.label || ((g) => g.value);
  const rows = groups.slice(0, opts.limit || 8).map((g) => h("div", {
    class: `mrow ${g.count > 1 ? "repeat" : ""} ${opts.hot && opts.hot(g) ? "hot" : ""}`,
    title: `${g.count} scam(s) · ${money(g.moved_out_cents / 100)} moved · click to filter`,
    onClick: () => setMemQuery(opts.query ? opts.query(g) : g.value) },
    h("div", { class: "mv" }, h("b", {}, label(g)), h("i", {}, opts.note ? opts.note(g) : (g.moved_out_cents ? money(g.moved_out_cents / 100) : ""))),
    h("div", { class: "sbar" }, h("i", { style: `width:${Math.round(100 * g.count / max)}%` })),
    h("div", { class: "mn" }, `${g.count}×`)));
  return h("div", { class: "card" }, h("h3", {}, title, h("span", {}, sub)),
    rows.length ? rows : h("p", { class: "muted tiny" }, "nothing yet"));
}

function renderMemPatterns(m) {
  const p = m.patterns;
  const vec = (v) => (v || "").replace(/_/g, " ");
  memEl("mem-patterns").replaceChildren(
    patternCard("lure themes", "the hook the email uses", p.themes),
    patternCard("sender domains", "where the emails come from", p.sender_domains, { note: (g) => g.vectors.map(vec).join(", ") }),
    patternCard("phishing hosts", "where the link sends the victim", p.phish_hosts),
    patternCard("playbook fingerprints", "op sequence once inside · L login R recon C contact S sweep X out D declined W cash",
      p.fingerprints, { label: (g) => `${g.value} · ${g.ops || "?"}`, note: (g) => [g.profile, g.ua_family, g.structured ? "structured" : null, g.lockout ? "lockout" : null].filter(Boolean).join(" · "), hot: (g) => g.count > 1 }),
    patternCard("mule accounts", "where the money went", p.mules,
      { label: (g) => "…" + g.value.slice(-8), note: (g) => `${g.grade} · ${money(g.moved_out_cents / 100)}`, hot: (g) => g.count > 1, query: (g) => g.value.slice(-8) }),
    patternCard("operator profiles + indicators", "how they behaved once inside", [...p.profiles, ...p.tags.map((g) => ({ ...g, value: vec(g.value) }))]));
}

function setMemQuery(q) {
  memQ = (q || "").toLowerCase();
  memEl("mem-q").value = memQ;
  memSig = ""; if (memData) renderMemTable(memData);
}

function renderMemTable(m) {
  const q = memQ.trim();
  const hay = (d) => [d.subject, d.sender, d.sender_domain, d.vector, d.profile, d.fingerprint, d.phish_host, d.grade, d.status,
    ...(d.themes || []), ...(d.tags || []), ...(d.mules || []), ...(d.secrets_leaked || [])].filter(Boolean).join(" ").toLowerCase();
  const rows = m.scams.filter((d) => !q || hay(d).includes(q));
  memEl("mem-table-title").textContent = q ? `scams matching “${q}”` : "all scams";
  memEl("mem-table-sum").textContent = `${rows.length} of ${m.scams.length} · ${money(rows.reduce((n, d) => n + d.moved_out_cents, 0) / 100)} drained`;
  if (!rows.length) return memEl("mem-table").replaceChildren(h("div", { class: "mem-empty" }, m.scams.length ? "no scam matches that filter" : "no scams remembered yet — detonate one from the inbox monitor"));
  const repeatFp = new Set(m.patterns.fingerprints.filter((g) => g.count > 1).map((g) => g.value));
  const repeatMule = new Set(m.patterns.mules.filter((g) => g.count > 1).map((g) => g.value));
  const head = h("tr", {}, ...["when", "scam", "lure", "vector", "drained", "mule", "operator", "fingerprint", "verdict"].map((t) => h("th", {}, t)));
  const body = rows.map((d) => h("tr", { class: "row", title: "open in the inbox monitor", onClick: () => { switchView("monitor"); select(d.id); } },
    h("td", { class: "sub nw" }, fmtTime(d.at), h("br"), shortDate(d.at)),
    h("td", {}, h("div", { style: "font-weight:600" }, d.subject || "(no subject)"), h("div", { class: "sub" }, d.sender || "—"),
      d.phish_host ? h("div", { class: "sub" }, "→ " + d.phish_host) : null),
    h("td", {}, h("div", { class: "pills" }, ...(d.themes || []).map((t) => h("span", { class: "pill" }, t)))),
    h("td", {}, (d.vector || "—").replace(/_/g, " "), d.secrets_leaked?.length ? h("div", { class: "sub" }, "leaked " + d.secrets_leaked.join(", ")) : null),
    h("td", { class: `num ${d.moved_out_cents ? "out" : ""}` }, d.moved_out_cents ? money(d.moved_out_cents / 100) : "—",
      d.transfers_out > 1 ? h("div", { class: "sub" }, `${d.transfers_out} transfers${d.structured ? " · structured" : ""}`) : null),
    h("td", { class: "nw" }, ...(d.mules || []).map((a) => h("div", { class: repeatMule.has(a) ? "fp repeat" : "sub" }, "…" + a.slice(-8) + (repeatMule.has(a) ? " ↺" : "")))),
    h("td", {}, d.profile || "—", h("div", { class: "sub" }, [d.ua_family, d.lockout ? "lockout" : null, d.third_party_logins ? `${d.third_party_logins} intruder login(s)` : null].filter(Boolean).join(" · "))),
    h("td", { class: `fp nw ${repeatFp.has(d.fingerprint) ? "repeat" : ""}` }, d.fingerprint ? `${d.fingerprint}${repeatFp.has(d.fingerprint) ? " ↺" : ""}` : "—", d.ops ? h("div", { class: "sub" }, d.ops) : null),
    h("td", { class: "nw" }, h("span", { class: `pill ${d.grade === "confirmed" ? "danger" : ""}` }, d.grade || d.status), h("div", { class: "sub" }, `risk ${d.risk_score}`))));
  memEl("mem-table").replaceChildren(h("table", { class: "dt" }, h("thead", {}, head), h("tbody", {}, ...body)));
}

memEl("mem-q").addEventListener("input", (e) => setMemQuery(e.target.value));
setInterval(() => { if (memVisible()) renderMemory(); }, 5000);
