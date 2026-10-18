import { live } from "./api.js";
import { mock } from "./mock.js";
import { session, getMode, setMode } from "./session.js";
import {
  h, money, signedMoney, mask, shortDate, greeting, spinner, alertBox, toast, copy, field, formData, busy,
} from "./ui.js";

// Pick the backend by mode. Both expose the same methods (api.js / mock.js).
const api = () => (getMode() === "demo" ? mock : live);

const app = document.getElementById("app");
const render = (...nodes) => app.replaceChildren(...nodes);

const TXN_LABEL = { transfer: "Transfer", deposit: "Deposit", withdrawal: "Withdrawal" };
const CREDIT = (t) => /credit/i.test(t || "");
const SAVINGS = (t) => /saving/i.test(t || "");

// --- chrome ---------------------------------------------------------------

function topbar(username, active) {
  const navItem = (label, route) =>
    h("button", { class: active === route ? "active" : "", onClick: () => go(route) }, label);
  return h("header", { class: "topbar" },
    h("div", { class: "brand", onClick: () => go("dashboard") },
      h("span", { class: "brand-mark" }, "US"), h("span", {}, "Bank of USA")),
    username && h("nav", { class: "nav" },
      navItem("Accounts", "dashboard"), navItem("Transfer", "transfer"), navItem("Deposit", "deposit")),
    h("div", { class: "topbar-right" },
      h("span", { class: `badge badge-${getMode()}` }, getMode() === "demo" ? "Demo" : "Live"),
      username && h("span", { class: "who" }, "@" + username),
      username && h("button", { class: "btn btn-ghost", onClick: logout }, "Sign out")));
}

function shell(username, active, ...content) {
  return [topbar(username, active), h("main", { class: "wrap" }, ...content),
    h("footer", { class: "foot" }, "Bank of USA · Equal Housing Lender · Member FDIC (simulation). Not a real bank; no real money moves.")];
}

// --- public bank homepage (sign-in) --------------------------------------

const SITE_NAV = ["Checking", "Savings & CDs", "Credit cards", "Home loans", "Auto", "Investing"];
const SITE_UTIL = ["Locations", "Help", "Contact us", "Español"];
const fakeLink = (e) => e.preventDefault();

function modeToggle() {
  const flip = (m) => () => { setMode(m); session.clear(); go("login"); };
  return h("div", { class: "mode-toggle-wrap" },
    h("div", { class: "mode-toggle", role: "tablist" },
      h("button", { class: `chip ${getMode() === "live" ? "chip-on" : ""}`, onClick: flip("live") }, "Live"),
      h("button", { class: `chip ${getMode() === "demo" ? "chip-on" : ""}`, onClick: flip("demo") }, "Demo")));
}

function siteHeader() {
  return h("div", { class: "site-head" },
    h("div", { class: "util-bar" }, h("div", { class: "util-wrap" },
      ...SITE_UTIL.map((l) => h("a", { href: "#", class: "util-link", onClick: fakeLink }, l)))),
    h("div", { class: "mast" }, h("div", { class: "mast-wrap" },
      h("div", { class: "brand site-brand", onClick: () => go("login") },
        h("span", { class: "brand-mark" }, "US"), h("span", {}, "Bank of USA")),
      h("nav", { class: "site-nav" },
        ...SITE_NAV.map((l) => h("a", { href: "#", class: "site-nav-link", onClick: fakeLink }, l))),
      h("div", { class: "mast-right" },
        h("span", { class: `badge badge-${getMode()}` }, getMode() === "demo" ? "Demo" : "Live")))));
}

function siteFooter() {
  const col = (title, items) => h("div", { class: "foot-col" }, h("h4", {}, title),
    ...items.map((i) => h("a", { href: "#", onClick: fakeLink }, i)));
  return h("footer", { class: "site-foot" },
    h("div", { class: "foot-cols" },
      col("Banking", ["Checking", "Savings & CDs", "Overdraft protection"]),
      col("Credit cards", ["Cash rewards", "Travel rewards", "Student cards"]),
      col("Loans", ["Home loans", "Auto loans", "Refinance"]),
      col("Investing", ["Brokerage", "Retirement", "Guided advice"]),
      col("Bank of USA", ["About us", "Careers", "Security", "Privacy"])),
    h("p", { class: "foot-legal" },
      "Bank of USA · Equal Housing Lender · Member FDIC (simulation). Not a real bank; no real money moves."));
}

const siteChrome = (...content) => [siteHeader(), ...content, siteFooter()];

// Secondary auth pages (enroll, verification): a centered card on the site chrome.
function authShell(title, subtitle, form, footer) {
  return siteChrome(h("main", { class: "auth-main" },
    h("div", { class: "card auth-card" },
      h("h2", {}, title), subtitle && h("p", { class: "muted" }, subtitle), form, footer, modeToggle(),
      getMode() === "demo" && h("p", { class: "muted tiny center mode-note" },
        "Demo mode runs entirely in this browser — no server needed."))));
}

function tile(accent, title, body) {
  return h("div", { class: "tile" },
    h("div", { class: "tile-bar", style: `background:${accent}` }),
    h("h3", {}, title), h("p", {}, body),
    h("a", { href: "#", class: "tile-link", onClick: fakeLink }, "Learn more →"));
}

function loginView() {
  const err = h("div");
  const form = h("form", { class: "signin-form", onSubmit: onSubmit },
    field("Username", h("input", { name: "username", autocomplete: "username", required: true, autofocus: true })),
    field("Password", h("input", { name: "password", type: "password", autocomplete: "current-password", required: true })),
    h("label", { class: "remember" }, h("input", { type: "checkbox" }), "Remember my username"),
    err,
    h("button", { class: "btn btn-primary btn-block", type: "submit" }, "Sign in"));

  async function onSubmit(e) {
    e.preventDefault();
    const { username, password } = formData(form);
    await busy(form, err, async () => {
      const res = await api().login(username, password);
      if (res?.status === "otp") return otpView(res);
      go("dashboard");
    });
  }

  const signin = h("div", { class: "signin-card" },
    h("h2", {}, "Sign in to Online Banking"), form,
    h("div", { class: "signin-links" },
      h("a", { href: "#", onClick: fakeLink }, "Forgot ID/Password?"),
      h("a", { href: "#", onClick: nav("signup") }, "Enroll now")),
    modeToggle());

  const hero = h("section", { class: "home-hero" }, h("div", { class: "hero-wrap" },
    h("div", { class: "hero-copy" },
      h("h1", {}, "Banking built around you."),
      h("p", {}, "Checking, savings, credit cards, and loans — all in one place, on web and mobile."),
      h("button", { class: "btn btn-light hero-cta", onClick: () => go("signup") }, "Open an account")),
    signin));

  const tiles = h("section", { class: "tiles" }, h("div", { class: "tiles-wrap" },
    tile("#e31837", "Everyday Checking", "No-monthly-fee options with overdraft protection built in."),
    tile("#012169", "High-Yield Savings", "Grow your balance with competitive rates and autosave."),
    tile("#e31837", "Cash Rewards Card", "Earn rewards on everyday spending, no annual fee."),
    tile("#012169", "Home Loans", "Buy or refinance with rates and tools to guide you.")));

  render(...siteChrome(hero, tiles));
}

function otpView(ctx) {
  const err = h("div");
  const form = h("form", { onSubmit: onSubmit },
    field("Verification code",
      h("input", { name: "code", inputmode: "numeric", autocomplete: "one-time-code", pattern: "[0-9]{6}",
        placeholder: "123456", required: true, autofocus: true }),
      "We sent a 6-digit code to the email on file."),
    err,
    h("button", { class: "btn btn-primary btn-block", type: "submit" }, "Verify & sign in"));

  async function onSubmit(e) {
    e.preventDefault();
    const { code } = formData(form);
    await busy(form, err, async () => {
      await api().verifyOtp(ctx.challengeId, code.trim(), ctx.username);
      go("dashboard");
    });
  }

  render(...authShell("Enter your code", "Two-step verification", form,
    h("p", { class: "auth-alt" }, "Wrong account? ", h("a", { href: "#", onClick: nav("login") }, "Start over"))));
}

function signupView() {
  const err = h("div");
  const form = h("form", { onSubmit: onSubmit },
    h("div", { class: "row" },
      field("First name", h("input", { name: "first_name", autocomplete: "given-name", required: true, autofocus: true })),
      field("Last name", h("input", { name: "last_name", autocomplete: "family-name", required: true }))),
    field("Username", h("input", { name: "username", autocomplete: "username", required: true, minlength: 3, pattern: "[A-Za-z0-9_.\\-]+" }),
      "Letters, numbers, dot, dash, underscore."),
    field("Password", h("input", { name: "password", type: "password", autocomplete: "new-password", required: true, minlength: 8 }),
      "At least 8 characters."),
    h("fieldset", { class: "fieldset" }, h("legend", {}, "Mailing address"),
      field("Street number", h("input", { name: "street_number", required: true })),
      field("Street name", h("input", { name: "street_name", autocomplete: "address-line1", required: true })),
      h("div", { class: "row" },
        field("City", h("input", { name: "city", autocomplete: "address-level2", required: true })),
        field("State", h("input", { name: "state", maxlength: 2, placeholder: "VA", required: true, style: "text-transform:uppercase" })),
        field("ZIP", h("input", { name: "zip", inputmode: "numeric", pattern: "[0-9]{5}", placeholder: "22101", required: true })))),
    err,
    h("button", { class: "btn btn-primary btn-block", type: "submit" }, "Create account"));

  async function onSubmit(e) {
    e.preventDefault();
    const f = formData(form);
    await busy(form, err, async () => {
      await api().signup({
        username: f.username, password: f.password, first_name: f.first_name, last_name: f.last_name,
        address: { street_number: f.street_number, street_name: f.street_name, city: f.city,
          state: f.state.toUpperCase(), zip: f.zip },
      });
      toast("Account created");
      go("dashboard");
    });
  }

  render(...authShell("Open your account", "Join Bank of USA in a few minutes", form,
    h("p", { class: "auth-alt" }, "Already have one? ", h("a", { href: "#", onClick: nav("login") }, "Sign in"))));
}

// --- dashboard ------------------------------------------------------------

function accountCard(a) {
  const credit = CREDIT(a.type), kind = credit ? "credit" : SAVINGS(a.type) ? "savings" : "checking";
  return h("button", { class: `acct ${kind}`, onClick: () => go("account", a.id) },
    h("div", { class: "acct-top" },
      h("span", { class: "acct-type" }, a.type),
      credit ? h("span", { class: "card-chip" }) : h("span", { class: "acct-num" }, mask(a.accountNumber))),
    h("div", { class: "acct-name" }, a.nickname),
    credit && h("div", { class: "acct-num" }, mask(a.accountNumber)),
    h("div", { class: "acct-bal" }, money(a.balance)),
    h("div", { class: "acct-foot" },
      a.rewards > 0 ? h("span", { class: "acct-rewards" }, a.rewards.toLocaleString() + " pts") : h("span"),
      h("span", { class: "acct-link" }, "View →")));
}

function accountGroup(title, list) {
  if (!list.length) return null;
  const sum = list.reduce((s, a) => s + a.balance, 0);
  return h("section", {},
    h("div", { class: "group-head" }, h("h3", {}, title), h("span", { class: "group-sum tnum" }, money(sum))),
    h("div", { class: "acct-grid" }, ...list.map(accountCard)));
}

async function dashboardView() {
  const username = session.get()?.username;
  render(...shell(username, "dashboard", spinner("Loading your accounts")));
  let customer, accounts;
  try {
    [customer, accounts] = await Promise.all([api().customer(), api().accounts()]);
  } catch (e) {
    return render(...shell(username, "dashboard", alertBox(e.message), retry(dashboardView)));
  }
  const banking = accounts.filter((a) => !CREDIT(a.type));
  const credit = accounts.filter((a) => CREDIT(a.type));
  const total = banking.reduce((sum, a) => sum + a.balance, 0);
  const noAcct = accounts.length === 0;
  render(...shell(username, "dashboard",
    h("section", { class: "hero" },
      h("p", { class: "hero-hi" }, `${greeting()}, ${customer.firstName || username}`),
      h("p", { class: "hero-label" }, "Total available balance"),
      h("p", { class: "hero-total tnum" }, money(total)),
      h("p", { class: "hero-meta" }, accounts.length
        ? `Across ${accounts.length} account${accounts.length > 1 ? "s" : ""}`
        : "No accounts yet"),
      h("div", { class: "hero-actions" },
        h("button", { class: "btn btn-light", disabled: noAcct, onClick: () => go("transfer") }, "Transfer money"),
        h("button", { class: "btn btn-outline", disabled: noAcct, onClick: () => go("deposit") }, "Deposit"))),
    h("div", { class: "section-head" }, h("h2", {}, "Your accounts"),
      h("button", { class: "btn btn-ghost", onClick: () => go("open") }, "+ Open account")),
    noAcct
      ? h("div", { class: "card empty" }, h("p", { class: "muted" }, "You don't have any accounts yet."),
          h("button", { class: "btn btn-primary", onClick: () => go("open") }, "Open your first account"))
      : h("div", {}, accountGroup("Banking", banking), accountGroup("Credit cards", credit))));
}

// --- account detail -------------------------------------------------------

function txnRow(t, accountId) {
  const incoming = t.kind === "deposit" || (t.kind === "transfer" && t.payeeId === accountId);
  const delta = (incoming ? 1 : -1) * t.amount;
  return h("li", { class: "txn" },
    h("div", { class: `txn-icon ${incoming ? "in" : "out"}` }, incoming ? "↓" : "↑"),
    h("div", { class: "txn-main" },
      h("div", { class: "txn-desc" }, t.description || TXN_LABEL[t.kind] || "Transaction"),
      h("div", { class: "txn-sub" }, [TXN_LABEL[t.kind], shortDate(t.date), t.status].filter(Boolean).join(" · "))),
    h("div", { class: `txn-amt ${incoming ? "in" : "out"}` }, signedMoney(delta)));
}

async function accountView(id) {
  const username = session.get()?.username;
  render(...shell(username, null, spinner("Loading account")));
  let account, activity;
  try {
    [account, activity] = await Promise.all([api().account(id), api().activity(id)]);
  } catch (e) {
    return render(...shell(username, null, backLink(), alertBox(e.message)));
  }
  activity.sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const credit = CREDIT(account.type);
  render(...shell(username, null, backLink(),
    h("section", { class: `card detail-hero ${credit ? "credit" : ""}` },
      h("div", { class: "detail-top" },
        h("div", {}, h("div", { class: "acct-type" }, account.type),
          h("h2", { class: "detail-name" }, account.nickname)),
        credit ? h("span", { class: "card-chip" })
          : h("div", { class: "detail-num" }, "Acct " + mask(account.accountNumber),
              h("button", { class: "btn btn-ghost tiny", onClick: () => copy(account.accountNumber), title: "Copy full number" }, "Copy"))),
      h("div", {},
        h("div", { class: "detail-bal-label" }, credit ? "Current balance" : "Available balance"),
        h("div", { class: "detail-bal tnum" }, money(account.balance))),
      h("div", { class: "hero-actions" },
        h("button", { class: "btn btn-light", onClick: () => go("transfer", id) }, "Transfer"),
        h("button", { class: "btn btn-outline", onClick: () => go("deposit", id) }, "Deposit"))),
    h("div", { class: "section-head" }, h("h2", {}, "Recent activity")),
    activity.length
      ? h("ul", { class: "txn-list card" }, ...activity.map((t) => txnRow(t, id)))
      : h("div", { class: "card empty" }, h("span", { class: "muted" }, "No transactions yet."))));
}

// --- transfer / deposit / open --------------------------------------------

function accountOption(a) {
  return h("option", { value: a.id }, `${a.nickname} (${mask(a.accountNumber)}) — ${money(a.balance)}`);
}

async function transferView(preselectFrom) {
  const username = session.get()?.username;
  render(...shell(username, "transfer", spinner("Loading")));
  let accounts;
  try { accounts = await api().accounts(); } catch (e) { return render(...shell(username, "transfer", backLink(), alertBox(e.message))); }
  if (!accounts.length) return render(...shell(username, "transfer", backLink(), alertBox("Open an account first.", "info")));

  const err = h("div");
  const fromSel = h("select", { name: "from", required: true }, ...accounts.map(accountOption));
  if (preselectFrom) fromSel.value = preselectFrom;
  const toInput = h("input", { name: "to", required: true, placeholder: "Recipient account id",
    list: "own-accts", autocomplete: "off" });
  const form = h("form", { class: "card form-card", onSubmit: onSubmit },
    field("From", fromSel),
    field("To", toInput, "Any Bank of USA account number. Your own accounts are suggested; paste another to send to someone else."),
    h("datalist", { id: "own-accts" }, ...accounts.map((a) => h("option", { value: a.id }, a.nickname))),
    field("Amount", h("input", { name: "amount", type: "number", min: "0.01", step: "0.01", required: true, placeholder: "0.00" })),
    field("Note", h("input", { name: "description", maxlength: 120, placeholder: "What's this for?" })),
    err,
    h("button", { class: "btn btn-primary btn-block", type: "submit" }, "Send transfer"));

  async function onSubmit(e) {
    e.preventDefault();
    const f = formData(form);
    await busy(form, err, async () => {
      await api().transfer({ fromId: f.from, toId: f.to.trim(), amount: f.amount, description: f.description });
      toast("Transfer sent");
      go("account", f.from);
    });
  }
  render(...shell(username, "transfer", backLink(), h("h1", { class: "page-title" }, "Transfer money"), form));
}

async function depositView(preselect) {
  const username = session.get()?.username;
  render(...shell(username, "deposit", spinner("Loading")));
  let accounts;
  try { accounts = await api().accounts(); } catch (e) { return render(...shell(username, "deposit", backLink(), alertBox(e.message))); }
  if (!accounts.length) return render(...shell(username, "deposit", backLink(), alertBox("Open an account first.", "info")));

  const err = h("div");
  const sel = h("select", { name: "account", required: true }, ...accounts.map(accountOption));
  if (preselect) sel.value = preselect;
  const form = h("form", { class: "card form-card", onSubmit: onSubmit },
    field("To account", sel),
    field("Amount", h("input", { name: "amount", type: "number", min: "0.01", step: "0.01", required: true, placeholder: "0.00" })),
    field("Note", h("input", { name: "description", maxlength: 120, placeholder: "e.g. Paycheck" })),
    err,
    h("button", { class: "btn btn-primary btn-block", type: "submit" }, "Add deposit"));

  async function onSubmit(e) {
    e.preventDefault();
    const f = formData(form);
    await busy(form, err, async () => {
      await api().deposit({ accountId: f.account, amount: f.amount, description: f.description });
      toast("Deposit added");
      go("account", f.account);
    });
  }
  render(...shell(username, "deposit", backLink(), h("h1", { class: "page-title" }, "Add a deposit"), form));
}

function openAccountView() {
  const username = session.get()?.username;
  const err = h("div");
  const form = h("form", { class: "card form-card", onSubmit: onSubmit },
    field("Account type", h("select", { name: "type", required: true },
      h("option", { value: "Checking" }, "Checking"), h("option", { value: "Savings" }, "Savings"),
      h("option", { value: "Credit Card" }, "Credit Card"))),
    field("Nickname", h("input", { name: "nickname", required: true, maxlength: 60, placeholder: "e.g. Everyday checking" })),
    err,
    h("button", { class: "btn btn-primary btn-block", type: "submit" }, "Open account"));

  async function onSubmit(e) {
    e.preventDefault();
    const f = formData(form);
    await busy(form, err, async () => {
      const a = await api().openAccount({ type: f.type, nickname: f.nickname });
      toast("Account opened");
      go("account", a.id);
    });
  }
  render(...shell(username, null, backLink(), h("h1", { class: "page-title" }, "Open a new account"), form));
}

// --- helpers & routing ----------------------------------------------------

const backLink = () => h("button", { class: "btn btn-ghost back", onClick: () => go("dashboard") }, "← Accounts");
const retry = (fn) => h("button", { class: "btn btn-light", onClick: fn }, "Try again");
const nav = (route) => (e) => { e.preventDefault(); go(route); };

async function logout() {
  try { await api().logout(); } catch { /* ignore */ }
  toast("Signed out");
  go("login");
}

const routes = {
  login: loginView, signup: signupView, dashboard: dashboardView, account: accountView,
  transfer: transferView, deposit: depositView, open: openAccountView,
};

function go(route, arg) {
  window.scrollTo(0, 0);
  if (!session.get() && !["login", "signup"].includes(route)) route = "login";
  (routes[route] || loginView)(arg);
}

window.addEventListener("session-expired", () => { toast("Session expired, please sign in", "error"); go("login"); });

go(session.get() ? "dashboard" : "login");
