// Live backend: the auth proxy (proxy/) reached through nginx at /bank-api. /auth/* is the proxy's own API; every
// other path is forwarded to Nessie unchanged. All Nessie paths and field names are in this file, so if the v2
// shapes differ from what is assumed here this is the only place to change.

import { session } from "./session.js";

const BASE = "/bank-api";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function errorMessage(data, status) {
  const d = data?.detail ?? data?.message ?? data;
  if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(1).join(".") || "input"}: ${e.msg}`).join("; ");
  if (typeof d === "string" && d) return d;
  if (status === 429) return "Too many attempts. Wait a minute and try again.";
  return `Request failed (${status})`;
}

async function request(method, path, body) {
  const s = session.get();
  const headers = { Accept: "application/json" };
  if (s) headers.Authorization = `Bearer ${s.token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let r;
  try {
    r = await fetch(BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Can't reach the bank server. Is docker compose up? (Or switch to demo mode.)");
  }
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (r.status === 401 && s && !path.startsWith("/auth/login")) {
    session.clear();
    window.dispatchEvent(new Event("session-expired"));
  }
  if (!r.ok) throw new ApiError(r.status, errorMessage(data, r.status));
  return data;
}

// Nessie v1 wraps created objects in {objectCreated}; v2 returns the object. Lists may be bare or wrapped.
const unwrap = (d) => d?.objectCreated ?? d;
const asList = (d) => (Array.isArray(d) ? d : d?.data ?? d?.items ?? d?.results ?? []);

// Nessie v2 stores money as integer cents (balance_cents / amount_cents); the mock uses dollars.
// Accept either so one normalizer serves both backends.
const toDollars = (cents, dollars) =>
  cents != null && cents !== "" ? Number(cents) / 100 : Number(dollars ?? 0);

export function normAccount(a) {
  return {
    id: a.id ?? a._id,
    type: a.type || "Checking",
    nickname: a.nickname || a.type || "Account",
    balance: toDollars(a.available_cents ?? a.balance_cents, a.balance),
    rewards: Number(a.rewards ?? 0),
    accountNumber: a.account_number ?? a.accountNumber ?? "",
    customerId: a.customer_id ?? a.customerId,
  };
}

export function normTxn(t, kind) {
  return {
    id: t.id ?? t._id,
    kind,
    date: t.transaction_date ?? t.created_at ?? t.date ?? "",
    status: t.status || "pending",
    amount: toDollars(t.amount_cents, t.amount),
    description: t.description || "",
    payerId: t.payer_id ?? t.payerId,
    payeeId: t.payee_id ?? t.payeeId,
  };
}

export function normCustomer(c) {
  return {
    id: c.id ?? c._id,
    firstName: c.first_name ?? "",
    lastName: c.last_name ?? "",
    address: c.address || null,
  };
}

function customerId() {
  const id = session.get()?.customer_id;
  if (!id) throw new ApiError(401, "Not signed in");
  return id;
}

export const live = {
  async signup(body) {
    const r = await request("POST", "/auth/signup", body);
    session.set({ ...r, username: body.username.toLowerCase(), mode: "live" });
    return { status: "ok" };
  },

  // Returns {status:"otp", challengeId, username} when a second factor is required, else {status:"ok"}.
  async login(username, password) {
    const r = await request("POST", "/auth/login", { username, password });
    if (r?.otp_required) return { status: "otp", challengeId: r.challenge_id, username: username.toLowerCase() };
    session.set({ ...r, username: username.toLowerCase(), mode: "live" });
    const me = await request("GET", "/auth/me"); // login doesn't return the customer id
    session.update({ customer_id: me.customer_id, username: me.username });
    return { status: "ok" };
  },

  async verifyOtp(challengeId, code, username) {
    const r = await request("POST", "/auth/verify-otp", { challenge_id: challengeId, code });
    session.set({ ...r, username, mode: "live" });
    return { status: "ok" };
  },

  async logout() {
    try { await request("POST", "/auth/logout"); } finally { session.clear(); }
  },

  async customer() {
    return normCustomer(unwrap(await request("GET", `/customers/${customerId()}`)));
  },

  async accounts() {
    try {
      return asList(await request("GET", `/customers/${customerId()}/accounts`)).map(normAccount);
    } catch (e) {
      if (e.status === 404) return [];
      throw e;
    }
  },

  async account(id) {
    return normAccount(unwrap(await request("GET", `/accounts/${encodeURIComponent(id)}`)));
  },

  async openAccount({ type, nickname }) {
    const r = await request("POST", `/customers/${customerId()}/accounts`,
      { type, nickname, rewards: 0, balance_cents: 0 });
    return normAccount(unwrap(r));
  },

  // Nessie v2 lists an account's activity at /transactions (the per-type paths are POST-only). Each
  // row carries its own kind (deposit|transfer|withdrawal). Deduplicate by id.
  async activity(accountId) {
    const id = encodeURIComponent(accountId);
    let rows;
    try {
      rows = asList(await request("GET", `/accounts/${id}/transactions`));
    } catch (e) {
      if (e.status === 404 || e.status === 405) return [];
      throw e;
    }
    const seen = new Set();
    return rows
      .map((t) => normTxn(t, (t.kind || t.type || "transaction").toLowerCase()))
      .filter((t) => !t.id || (!seen.has(t.id) && seen.add(t.id)));
  },

  async transfer({ fromId, toId, amount, description }) {
    const r = await request("POST", `/accounts/${encodeURIComponent(fromId)}/transfers`, {
      medium: "balance", payee_id: toId, amount_cents: toCents(amount), description,
    });
    return normTxn(unwrap(r) || {}, "transfer");
  },

  async deposit({ accountId, amount, description }) {
    const r = await request("POST", `/accounts/${encodeURIComponent(accountId)}/deposits`, {
      medium: "balance", amount_cents: toCents(amount), description,
    });
    return normTxn(unwrap(r) || {}, "deposit");
  },
};

const toCents = (dollars) => Math.round(Number(dollars) * 100);
