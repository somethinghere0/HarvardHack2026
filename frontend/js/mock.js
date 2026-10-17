// Demo backend: same interface as live (api.js), kept in this browser's localStorage so the UI runs without the
// proxy or a Nessie key. Sign up in demo mode to create a user; nothing leaves the browser.

import { ApiError, normAccount, normCustomer, normTxn } from "./api.js";
import { session } from "./session.js";

const KEY = "hb.mock.v2";
const wait = () => new Promise((r) => setTimeout(r, 200));
const hex = (n) => Array.from(crypto.getRandomValues(new Uint8Array(n)), (b) => b.toString(16).padStart(2, "0")).join("");
const newId = () => hex(12); // 24 hex chars, like a Nessie id
const accountNumber = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b % 10).join("");
const today = () => new Date().toISOString().slice(0, 10);

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || { users: {}, customers: {}, accounts: {}, txns: [], sessions: {} };
  } catch {
    return { users: {}, customers: {}, accounts: {}, txns: [], sessions: {} };
  }
}
function save(s) {
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* storage blocked: state lasts for this page only */ }
}

function startSession(s, username) {
  const token = hex(32);
  const expires_at = new Date(Date.now() + 12 * 3600e3).toISOString();
  s.sessions[token] = username;
  session.set({ token, expires_at, username, customer_id: s.users[username].customerId, mode: "demo" });
}

function current(s) {
  const tok = session.get()?.token;
  const username = tok && s.sessions[tok];
  if (!username) {
    session.clear();
    window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(401, "Invalid or expired session");
  }
  return s.users[username].customerId;
}

function ownAccount(s, cid, id) {
  const a = s.accounts[id];
  if (!a || a.customer_id !== cid) throw new ApiError(404, "Account not found");
  return a;
}

function positiveAmount(amount) {
  const n = Math.round(Number(amount) * 100) / 100;
  if (!(n > 0)) throw new ApiError(422, "Amount must be greater than zero");
  return n;
}

export const mock = {
  async signup(body) {
    await wait();
    const s = load();
    const username = body.username.toLowerCase();
    if (s.users[username]) throw new ApiError(409, "Username already taken");
    const customerId = newId();
    s.customers[customerId] = { id: customerId, first_name: body.first_name, last_name: body.last_name, address: body.address };
    // Demo mode only: a plaintext password in this browser's storage, compared on login.
    s.users[username] = { password: body.password, customerId };
    startSession(s, username);
    save(s);
  },

  async login(username, password) {
    await wait();
    const s = load();
    const u = s.users[username.toLowerCase()];
    if (!u || u.password !== password) throw new ApiError(401, "Invalid username or password");
    startSession(s, username.toLowerCase());
    save(s);
  },

  async logout() {
    const s = load();
    delete s.sessions[session.get()?.token];
    save(s);
    session.clear();
  },

  async customer() {
    await wait();
    const s = load();
    return normCustomer(s.customers[current(s)]);
  },

  async accounts() {
    await wait();
    const s = load();
    const cid = current(s);
    return Object.values(s.accounts).filter((a) => a.customer_id === cid).map(normAccount);
  },

  // Any account id resolves (like the shared Nessie tenant), so a transfer can target someone else's account.
  async account(id) {
    await wait();
    const s = load();
    current(s);
    const a = s.accounts[id];
    if (!a) throw new ApiError(404, "Account not found");
    return normAccount(a);
  },

  async openAccount({ type, nickname }) {
    await wait();
    const s = load();
    const cid = current(s);
    const id = newId();
    s.accounts[id] = { id, type, nickname, rewards: 0, balance: 0, account_number: accountNumber(), customer_id: cid };
    save(s);
    return normAccount(s.accounts[id]);
  },

  async activity(accountId) {
    await wait();
    const s = load();
    current(s);
    return s.txns
      .filter((t) => t.payer_id === accountId || t.payee_id === accountId)
      .map((t) => normTxn(t, t.kind));
  },

  async transfer({ fromId, toId, amount, description }) {
    await wait();
    const s = load();
    const from = ownAccount(s, current(s), fromId);
    const to = s.accounts[toId];
    if (!to) throw new ApiError(404, "Recipient account not found");
    if (toId === fromId) throw new ApiError(422, "Pick a different account to send to");
    const n = positiveAmount(amount);
    if (n > from.balance) throw new ApiError(422, "Insufficient funds");
    from.balance = Math.round((from.balance - n) * 100) / 100;
    to.balance = Math.round((to.balance + n) * 100) / 100;
    const t = { id: newId(), kind: "transfer", payer_id: fromId, payee_id: toId, amount: n, description,
      status: "executed", transaction_date: today() };
    s.txns.push(t);
    save(s);
    return normTxn(t, "transfer");
  },

  async deposit({ accountId, amount, description }) {
    await wait();
    const s = load();
    const a = ownAccount(s, current(s), accountId);
    const n = positiveAmount(amount);
    a.balance = Math.round((a.balance + n) * 100) / 100;
    const t = { id: newId(), kind: "deposit", payee_id: accountId, amount: n, description,
      status: "executed", transaction_date: today() };
    s.txns.push(t);
    save(s);
    return normTxn(t, "deposit");
  },
};
