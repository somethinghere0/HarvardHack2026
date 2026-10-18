// Fraud-monitor dashboard. Reads the orchestrator (/api) and renders the engagement list, timeline,
// indicators, and the captured decoy persona. Everything is built with createElement/textContent so
// scammer-supplied strings are never parsed as HTML. Internal tool — not linked from the bait site.
import { h, money, shortDate } from "./ui.js";

const API = "/api";
const listEl = document.getElementById("list");
const panelEl = document.getElementById("panel");
const countEl = document.getElementById("count");
let selected = null;

async function api(path, opts) {
  const r = await fetch(API + path, opts);
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

const riskClass = (n) => (n >= 60 ? "risk-hi" : n >= 30 ? "risk-md" : "risk-lo");
const fmtTime = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" }); };

function engItem(e) {
  const btn = h("button", { class: `eng ${e.status} ${selected === e.id ? "sel" : ""}`, onClick: () => select(e.id) },
    h("div", { class: "eng-row" },
      h("span", { class: "eng-sub" }, e.subject || e.scammer_email || "(no subject)"),
      h("span", { class: `risk ${riskClass(e.risk_score)}` }, String(e.risk_score))),
    h("div", { class: "tiny muted" }, (e.scammer_email || "—") + " · " + e.status),
    h("div", { class: "pills" }, ...(e.tags || []).map((t) => h("span", { class: "pill danger" }, t.replace(/_/g, " ")))));
  return btn;
}

async function renderStatus() {
  try {
    const st = await api("/status");
    const strip = document.getElementById("status");
    const cls = (m) => (["live", "app_password", "oauth"].includes(m) ? "live"
      : m === "polling" || m === "local" ? "local" : "fake");  // 'missing' shows grey
    const chip = (name, mode) => h("span", { class: `svc ${cls(mode)}` },
      h("span", { class: "dot" }), `${name}: ${mode}`);
    strip.replaceChildren(...Object.entries(st.services).map(([k, v]) => chip(k, v)));
  } catch { /* status is best-effort */ }
}

async function renderInbox() {
  try {
    const { messages } = await api("/messages");
    const el = document.getElementById("inbox");
    document.getElementById("inbox-count").textContent =
      `${messages.length} vetted · ${messages.filter((m) => m.verdict === "scam").length} scam`;
    el.replaceChildren(...messages.map((m) => {
      const scam = m.verdict === "scam";
      const node = h("button", { class: `msg ${scam ? "scam" : "safe"}`,
        onClick: scam && m.engagement_id ? () => select(m.engagement_id) : null },
        h("span", { class: "vtag" }, m.verdict),
        h("div", { style: "min-width:0" },
          h("div", { class: "msub" }, m.subject || "(no subject)"),
          h("div", { class: "mfrom" }, (m.sender || "") + (m.vector ? ` · ${m.vector}` : ""))),
        h("span", { class: "maction" }, m.action || ""));
      return node;
    }));
  } catch { /* inbox is best-effort */ }
}

async function refresh() {
  await renderInbox();
  const { engagements } = await api("/engagements");
  countEl.textContent = `${engagements.length} engagement${engagements.length === 1 ? "" : "s"}`;
  listEl.replaceChildren(...engagements.map(engItem));
  if (selected) renderDetail(selected).catch(() => {});
}

async function select(id) {
  selected = id;
  [...listEl.children].forEach((c) => c.classList.toggle("sel", false));
  await refresh();
  await renderDetail(id);
}

function kv(label, value, mono) {
  return [h("dt", {}, label), h("dd", { class: mono ? "mono" : "" }, value ?? "—")];
}

async function renderDetail(id) {
  const d = await api(`/engagements/${id}`);
  const eng = d.engagement;
  const persona = (d.events.find((e) => e.type === "persona.created") || {}).data || {};
  const ind = d.indicators || { indicators: [], risk_score: 0 };

  const personaCard = h("div", { class: "card" },
    h("h3", { style: "font-size:14px;margin-bottom:10px" }, "Decoy persona"),
    h("dl", { class: "kv" },
      ...kv("Name", persona.name),
      ...kv("Login", persona.username, true),
      ...kv("Email", persona.email, true),
      ...kv("Customer id", persona.customer_id, true),
      ...kv("Accounts", (persona.accounts || []).join(", "), true)));

  const indCard = h("div", { class: "card" },
    h("h3", { style: "font-size:14px;margin-bottom:10px" },
      `Indicators — risk ${ind.risk_score}/100`),
    ind.indicators.length
      ? h("div", { class: "bars" }, ...ind.indicators.map((i) =>
          h("div", { class: "bar" },
            h("span", {}, i.label), h("span", { class: "mono" }, "+" + i.weight),
            h("div", { class: "track" }, h("div", { class: "fill", style: `width:${Math.min(100, i.weight * 4)}%` })))))
      : h("p", { class: "muted tiny" }, "No fraud indicators yet."));

  const timeline = h("div", { class: "card" },
    h("h3", { style: "font-size:14px;margin-bottom:10px" }, "Timeline"),
    h("ul", { class: "tl" }, ...d.events.map((ev) =>
      h("li", {},
        h("span", { class: "t" }, fmtTime(ev.created_at)),
        h("span", { class: "src" }, ev.source),
        h("span", {}, ev.type + eventDetail(ev))))));

  const sandboxCard = buildSandbox(d);

  const emails = d.emails.length ? h("div", { class: "card" },
    h("h3", { style: "font-size:14px;margin-bottom:10px" }, "Messages"),
    ...d.emails.map((m) => h("div", { style: "border-bottom:1px solid var(--line-2);padding:8px 0" },
      h("div", { class: "tiny muted" }, `${m.direction === "in" ? "⬇" : "⬆"} ${m.kind} · ${m.sender || ""} → ${m.recipient || ""}`),
      h("div", { style: "font-weight:600;font-size:13px" }, m.subject || ""),
      h("div", { class: "tiny", style: "white-space:pre-wrap;color:var(--muted)" }, (m.body || "").slice(0, 400))))) : null;

  panelEl.replaceChildren(h("div", { class: "panel" },
    h("div", { class: "eng-row" },
      h("h2", { style: "font-size:18px" }, eng.subject || "Engagement"),
      h("span", { class: `risk ${riskClass(eng.risk_score)}`, style: "font-size:22px" }, eng.risk_score + "/100")),
    eng.summary && h("p", { class: "muted", style: "margin:-6px 0 2px" }, eng.summary),
    h("div", { class: "pills" }, h("span", { class: "pill" }, eng.status), ...(eng.tags || []).map((t) => h("span", { class: "pill danger" }, t.replace(/_/g, " ")))),
    sandboxCard, personaCard, indCard, timeline, emails));

  const term = panelEl.querySelector(".sb-term");
  if (term) term.scrollTop = term.scrollHeight;  // keep the terminal pinned to the newest line
}

// --- Daytona sandbox viewer: watch the agent work inside the container -------

function buildSandbox(d) {
  const ev = d.events || [];
  const shots = d.shots || [];
  const has = ev.some((e) => ["sandbox.launching", "agent.started", "agent.step"].includes(e.type));
  if (!has && !shots.length) return null;

  const finished = ev.some((e) => ["sandbox.finished", "agent.finished", "agent.error"].includes(e.type));
  const errored = ev.some((e) => e.type === "agent.error");
  const running = !finished;
  const sid = (ev.find((e) => e.type === "sandbox.created")?.data?.sandbox_id)
    || "sbx-" + (d.engagement?.id || "").slice(0, 8);
  const target = ev.find((e) => e.type === "portal.detected")?.data?.url
    || ev.find((e) => e.type === "sandbox.launching")?.data?.bank || "";
  const lastStep = [...ev].reverse().find((e) => e.type === "agent.step");
  const url = (lastStep?.data?.url) || target || "about:blank";
  const shot = shots[shots.length - 1];

  const lines = termLines(ev);
  const term = h("div", { class: "sb-term" },
    h("div", { class: "ln dim" }, h("span", { class: "lt" }, ""), "daytona cloud · ephemeral sandbox"),
    ...lines.map((l) => h("div", { class: `ln ${l.cls || ""}` }, h("span", { class: "lt" }, l.t), l.text)),
    running ? h("div", { class: "ln cur" }, h("span", { class: "lt" }, ""), h("span", { class: "blink" }, "▋")) : null);

  const view = h("div", { class: "sb-view" },
    h("div", { class: "sb-chrome" },
      h("span", { class: "c-dots" }, h("i"), h("i"), h("i")),
      h("span", { class: "c-url" }, shortUrl(url))),
    shot
      ? h("img", { class: "sb-screen", src: shot.image, alt: shot.label || "" })
      : h("div", { class: "sb-boot" }, h("span", { class: "spin" }), "booting chromium runtime…"));

  return h("div", { class: `sandbox ${running ? "run" : errored ? "err" : "done"}` },
    h("div", { class: "sb-bar" },
      h("span", { class: "c-dots" }, h("i"), h("i"), h("i")),
      h("span", { class: "sb-title" }, `daytona ◦ ${sid}`),
      h("span", { class: "sb-state" }, running ? "● running" : errored ? "✗ error" : "○ terminated")),
    h("div", { class: "sb-body" }, term, view));
}

const _GLYPH = { err: "✗", ok: "✓", cmd: "$", step: "▸" };
function termLines(events) {
  const out = [];
  const push = (t, text, cls) => out.push({ t: fmtTime(t), text: `${_GLYPH[cls] || "▸"} ${text}`, cls: cls === "err" ? "err" : cls === "ok" ? "ok" : cls === "cmd" ? "cmd" : "" });
  for (const e of events) {
    const x = e.data || {}, t = e.created_at;
    switch (e.type) {
      case "sandbox.launching": push(t, `daytona create --snapshot chromium`, "cmd"); push(t, `pip install playwright anthropic · launching chromium`, "cmd"); break;
      case "sandbox.created": push(t, `sandbox ${x.sandbox_id || ""} ready`, "ok"); break;
      case "agent.started": push(t, `agent online → ${shortUrl(x.bank || x.portal || "")}`); break;
      case "agent.step": push(t, x.observation || `step @ ${shortUrl(x.url || "")}`); break;
      case "otp.sent": push(t, `one-time code issued to inbox`); break;
      case "agent.otp_relayed": push(t, `OTP ${x.got ? "read from inbox, entered ✓" : "requested…"}`, x.got ? "ok" : ""); break;
      case "session.login": push(t, `signed in as @${x.username || "victim"}`, "ok"); break;
      case "payee.added": push(t, `added external payee ${String(x.payee_id || "").slice(-6)}`); break;
      case "transfer.created": push(t, `transfer ${money((x.amount_cents || 0) / 100)} → mule`); break;
      case "scammer.drain": case "engagement.drained": push(t, `account drained · ${money((x.moved_cents || 0) / 100)} moved`, "ok"); break;
      case "agent.finished": push(t, `sequence complete`, "ok"); break;
      case "sandbox.finished": push(t, `daytona sandbox delete`, "cmd"); break;
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
refresh().catch((e) => { panelEl.replaceChildren(h("div", { class: "empty-panel" }, "Can't reach the orchestrator at /api. Is it running?")); console.error(e); });
setInterval(() => refresh().catch(() => {}), 3000);
