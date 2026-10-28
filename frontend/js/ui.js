// Tiny DOM helpers. Everything is built with createElement/textContent, so values from the API are never parsed
// as HTML.

export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
export const money = (n) => usd.format(Number(n) || 0);

export function signedMoney(n) {
  return (n < 0 ? "−" : "+") + usd.format(Math.abs(n));
}

export function mask(accountNumber) {
  const s = String(accountNumber || "");
  return s ? "•••• " + s.slice(-4) : "••••";
}

export function shortDate(iso) {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
  return isNaN(d) ? iso : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function greeting() {
  const hr = new Date().getHours();
  return hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
}

export function spinner(label = "Loading") {
  return h("div", { class: "loading", role: "status" }, h("span", { class: "spin" }), label + "…");
}

export function alertBox(message, kind = "error") {
  return h("div", { class: `alert alert-${kind}`, role: kind === "error" ? "alert" : "status" }, message);
}

let toastTimer;
export function toast(message, kind = "ok") {
  let el = document.getElementById("toast");
  if (!el) document.body.append((el = h("div", { id: "toast", "aria-live": "polite" })));
  el.className = `toast toast-${kind} show`;
  el.textContent = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

export async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied to clipboard");
  } catch {
    toast("Couldn't copy, select it manually", "error");
  }
}

// Form field: label + input with an id, plus optional hint.
let fieldSeq = 0;
export function field(label, input, hint) {
  const id = input.id || (input.id = `f${++fieldSeq}`);
  return h("div", { class: "field" }, h("label", { for: id }, label), input, hint && h("small", { class: "hint" }, hint));
}

export function formData(form) {
  return Object.fromEntries(new FormData(form).entries());
}

// Disable a form's submit button while `fn` runs, and show its error in `errorSlot`.
export async function busy(form, errorSlot, fn) {
  const btn = form.querySelector("[type=submit]");
  const label = btn?.textContent;
  if (btn) { btn.disabled = true; btn.textContent = "Please wait…"; }
  errorSlot.replaceChildren();
  try {
    return await fn();
  } catch (e) {
    errorSlot.replaceChildren(alertBox(e.message || "Something went wrong"));
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}
