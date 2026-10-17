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

async function refresh() {
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
    personaCard, indCard, timeline, emails));
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

refresh().catch((e) => { panelEl.replaceChildren(h("div", { class: "empty-panel" }, "Can't reach the orchestrator at /api. Is it running?")); console.error(e); });
setInterval(() => refresh().catch(() => {}), 3000);
