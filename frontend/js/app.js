import { live } from "./api.js";
import { mock } from "./mock.js";
import { session, getMode, setMode } from "./session.js";
import { siteHeader, siteFooter, homepage, promoBanner, cookieBanner } from "./landing.js";
import {
  olbHeader, olbTabs, olbFooter, promoStrip, activityCenter, rewardsBlurb, note, icons, svg,
} from "./portal.js";
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
const last4 = (n) => String(n || "").slice(-4) || "0000";
const fakeLink = (e) => e.preventDefault();
const nav = (route, arg) => (e) => { e.preventDefault(); go(route, arg); };

const badge = () => h("span", { class: `badge badge-${getMode()}` }, getMode() === "demo" ? "Demo" : "Live");

// --- signed-in chrome (Online Banking) ------------------------------------

function shell(active, ...content) {
  document.body.classList.remove("landing");
  document.body.classList.add("portal");
  return [
    olbHeader({ badge: badge(), onHome: () => go("dashboard"), onLogout: logout }),
    olbTabs(active, go),
    h("main", { class: "olb-main" }, h("div", { class: "olb-wrap" }, ...content)),
    olbFooter(),
  ];
}

// --- public bank homepage (sign-in) --------------------------------------

function modeToggle() {
  const flip = (m) => () => { setMode(m); session.clear(); go("login"); };
  return h("div", { class: "mode-toggle-wrap" },
    h("div", { class: "mode-toggle", role: "tablist" },
      h("button", { class: `chip ${getMode() === "live" ? "chip-on" : ""}`, onClick: flip("live") }, "Live"),
      h("button", { class: `chip ${getMode() === "demo" ? "chip-on" : ""}`, onClick: flip("demo") }, "Demo")));
}

// Public pages get the retail-bank chrome (header, footer, banners); signed-in pages use the portal shell.
function siteChrome(...content) {
  document.body.classList.remove("portal");
  document.body.classList.add("landing");
  return [siteHeader({ badge: badge(), onBrand: () => go("login") }), ...content, siteFooter(), promoBanner(), cookieBanner()];
}

// Secondary auth pages (enroll, verification): a centered card on the site chrome.
function authShell(title, subtitle, form, footer) {
  return siteChrome(h("main", { class: "auth-main" },
    h("div", { class: "card auth-card" },
      h("h2", {}, title), subtitle && h("p", { class: "muted" }, subtitle), form, footer, modeToggle(),
      getMode() === "demo" && h("p", { class: "muted tiny center mode-note" },
        "Demo mode runs entirely in this browser — no server needed."))));
}

function loginView() {
  const err = h("div");
  const form = h("form", { class: "signin-form", onSubmit: onSubmit },
    field("User ID", h("input", { name: "username", autocomplete: "username", required: true, autofocus: true })),
    field("Password", h("input", { name: "password", type: "password", autocomplete: "current-password", required: true })),
    h("label", { class: "remember" }, h("input", { type: "checkbox" }), "Save user ID"),
    err,
    h("button", { class: "btn btn-primary btn-block", type: "submit" }, "Log in"));

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
      h("a", { href: "#", onClick: fakeLink }, "Forgot user ID/password"),
      h("div", { class: "pair" },
        h("a", { href: "#", onClick: fakeLink }, "Security & Help"),
        h("a", { href: "#", onClick: nav("signup") }, "Enroll"))),
    modeToggle());

  render(...siteChrome(h("main", {}, ...homepage(signin, { onOpen: () => go("signup") }))));
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

// --- accounts overview ----------------------------------------------------

const miniFlag = () => svg(icons.flag, "mini-flag");

function acctRow(a) {
  const credit = CREDIT(a.type);
  return h("a", { href: "#", class: "acct-row", onClick: nav("account", a.id) },
    h("span", { class: "acct-row-main" },
      h("span", { class: "acct-row-name" }, `${a.nickname} - ${last4(a.accountNumber)}`),
      h("span", { class: "acct-row-sub" }, "Quick View", h("span", { class: "bar" }, "|"), credit ? "Pay now" : "Transfer")),
    h("span", { class: "acct-row-bal" },
      h("strong", {}, money(a.balance)),
      h("small", {}, credit ? "Current balance" : "Available balance")));
}

function acctGroup(title, list, sumLabel) {
  if (!list.length) return null;
  const sum = list.reduce((s, a) => s + a.balance, 0);
  return h("section", { class: "acct-panel" },
    h("div", { class: "acct-group-head" }, miniFlag(), title, h("span", { class: "sum" }, `${sumLabel}: ${money(sum)}`)),
    ...list.map(acctRow));
}

async function dashboardView() {
  render(...shell("dashboard", spinner("Loading your accounts")));
  let customer, accounts;
  try {
    [customer, accounts] = await Promise.all([api().customer(), api().accounts()]);
  } catch (e) {
    return render(...shell("dashboard", alertBox(e.message), retry(dashboardView)));
  }
  const banking = accounts.filter((a) => !CREDIT(a.type));
  const credit = accounts.filter((a) => CREDIT(a.type));
  const username = session.get()?.username;
  const name = [customer.firstName, customer.lastName].filter(Boolean).join(" ") || username;
  const since = new Date().toLocaleDateString("en-US", { month: "short", year: "numeric" });

  const left = h("div", {},
    promoStrip(icons.pie, "Launch Spending & Budgeting",
      "Get trends and analysis across accounts and watch the money leave in real time."),
    promoStrip(icons.zilch, "Set up Zilch®",
      "Send money to friends and family who will absolutely pay you back.", () => go("transfer")),
    accounts.length
      ? [acctGroup("Bank accounts", banking, "Total"), acctGroup("Credit cards", credit, "Total owed")]
      : h("section", { class: "acct-panel" },
          h("div", { class: "acct-group-head" }, miniFlag(), "Bank accounts"),
          h("div", { class: "empty-accts" }, "You don’t have any accounts yet. This is the safest a bank account has ever been.",
            h("button", { class: "btn btn-primary", onClick: () => go("open") }, "Open your first account"))),
    accounts.length ? h("div", { class: "acct-panel-foot" },
      h("a", { href: "#", onClick: nav("open") }, "Open a new account"),
      h("a", { href: "#", onClick: nav("deposit") }, "Deposit a check"),
      h("span", { class: "muted tiny" }, `${greeting()}. Balances are current as of right now, give or take.`)) : null);

  render(...shell("dashboard",
    h("div", { class: "olb-greet" },
      h("h1", {}, name,
        h("span", { class: "greet-links" },
          h("a", { href: "#", onClick: fakeLink }, "Update Profile"), h("span", { class: "bar" }, "|"),
          h("a", { href: "#", onClick: fakeLink }, "Security Center"))),
      rewardsBlurb(since)),
    h("div", { class: "olb-two" }, left, activityCenter(go))));
}

// --- account detail -------------------------------------------------------

function isIncoming(t, accountId) {
  return t.kind === "deposit" || (t.kind === "transfer" && t.payeeId === accountId);
}

function txnTable(account, activity) {
  // Running balance: newest first, so each row's balance is the current balance minus everything newer.
  let running = account.balance;
  const rows = activity.map((t) => {
    const incoming = isIncoming(t, account.id);
    const delta = (incoming ? 1 : -1) * t.amount;
    const bal = running;
    running -= delta;
    const pending = /pending|processing/i.test(t.status || "");
    return h("tr", {},
      h("td", { class: "date" }, shortDate(t.date)),
      h("td", { class: "desc" }, h("a", { href: "#", onClick: fakeLink }, t.description || TXN_LABEL[t.kind] || "Transaction")),
      h("td", {}, TXN_LABEL[t.kind] || "Other"),
      h("td", { class: pending ? "pending" : "" }, pending ? "Processing" : "Posted"),
      h("td", { class: `num ${incoming ? "credit" : ""}` }, signedMoney(delta)),
      h("td", { class: "num" }, pending ? "—" : money(bal)));
  });
  return h("table", { class: "txn-table" },
    h("thead", {}, h("tr", {}, ...["Date", "Description", "Type", "Status", "Amount", "Balance"].map((c) => h("th", {}, c)))),
    h("tbody", {}, ...rows));
}

async function accountView(id) {
  render(...shell("dashboard", spinner("Loading account")));
  let account, activity;
  try {
    [account, activity] = await Promise.all([api().account(id), api().activity(id)]);
  } catch (e) {
    return render(...shell("dashboard", crumb(), alertBox(e.message)));
  }
  activity.sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const credit = CREDIT(account.type);
  const pendingSum = activity.filter((t) => /pending|processing/i.test(t.status || ""))
    .reduce((s, t) => s + (isIncoming(t, id) ? 1 : -1) * t.amount, 0);

  const filterSel = h("select", { "aria-label": "Show" },
    h("option", { value: "" }, "All transactions"), h("option", { value: "deposit" }, "Deposits"),
    h("option", { value: "transfer" }, "Transfers"), h("option", { value: "withdrawal" }, "Withdrawals"));
  const search = h("input", { type: "search", placeholder: "Search transactions", "aria-label": "Search transactions" });
  const tableSlot = h("div");
  const redraw = () => {
    const q = search.value.trim().toLowerCase();
    const list = activity.filter((t) => (!filterSel.value || t.kind === filterSel.value) &&
      (!q || (t.description || TXN_LABEL[t.kind] || "").toLowerCase().includes(q)));
    tableSlot.replaceChildren(list.length ? txnTable(account, list)
      : h("div", { class: "txn-empty" }, activity.length ? "No transactions match." : "No transactions for this account. Suspiciously quiet."));
  };
  filterSel.addEventListener("change", redraw);
  search.addEventListener("input", redraw);
  redraw();

  const tab = (label, on) => h("button", { class: `sub-tab ${on ? "on" : ""}`, type: "button", onClick: fakeLink }, label);
  const stat = (label, value, big) => h("div", {},
    h("div", { class: "sum-label" }, label, svg(icons.info, "ico ico-xs")),
    h("div", { class: big ? "sum-big" : "sum-val" }, value));

  render(...shell("dashboard", crumb(),
    h("div", { class: "detail-head" },
      h("h1", {}, account.nickname, h("small", {}, `${account.type} - ${last4(account.accountNumber)}`)),
      h("div", { class: "detail-num muted tiny" }, "Account number: ", mask(account.accountNumber), " ",
        h("button", { class: "btn btn-ghost tiny", onClick: () => copy(account.accountNumber) }, "Show"))),
    h("div", { class: "sub-tabs" },
      tab("Activity", true), tab("Information & Services"), tab("Statements & Documents"), tab(credit ? "Rewards (none)" : "Rewards")),
    h("section", { class: "summary" },
      stat(credit ? "Current balance" : "Available balance", money(account.balance), true),
      credit ? stat("Minimum payment due", money(Math.min(account.balance, 25))) : stat("Current balance", money(account.balance - pendingSum)),
      credit ? stat("Payment due date", "Eventually") : stat("Pending", money(pendingSum)),
      h("div", { class: "sum-actions" },
        h("button", { class: "btn btn-primary", onClick: () => go("transfer", id) }, credit ? "Make a payment" : "Transfer"),
        h("button", { class: "btn btn-secondary", onClick: () => go("deposit", id) }, "Deposit"))),
    h("div", { class: "txn-toolbar" },
      h("label", {}, "Show:", filterSel), h("label", {}, "Search:", search),
      h("a", { href: "#", class: "right", onClick: fakeLink }, svg(icons.down, "ico ico-sm"), "Download")),
    tableSlot,
    h("p", { class: "txn-foot" }, "Transactions post in the order they happened, mostly. Running balance shown for posted transactions only.")));
}

// --- transfer / deposit / open --------------------------------------------

function accountOption(a) {
  return h("option", { value: a.id }, `${a.nickname} - ${last4(a.accountNumber)} (${money(a.balance)})`);
}

const today = () => new Date().toLocaleDateString("en-US", { month: "2-digit", day: "2-digit", year: "numeric" });

function formPage(active, title, form, side) {
  return shell(active, crumb(), h("h1", { class: "olb-page-title" }, title),
    h("div", { class: "olb-two" }, form, h("aside", { class: "olb-side" }, ...side)));
}

async function transferView(preselectFrom) {
  render(...shell("transfer", spinner("Loading")));
  let accounts;
  try { accounts = await api().accounts(); } catch (e) { return render(...shell("transfer", crumb(), alertBox(e.message))); }
  if (!accounts.length) return render(...shell("transfer", crumb(), alertBox("Open an account first.", "info")));

  const err = h("div");
  const fromSel = h("select", { name: "from", required: true }, ...accounts.map(accountOption));
  if (preselectFrom) fromSel.value = preselectFrom;
  const toInput = h("input", { name: "to", required: true, placeholder: "Recipient account number", list: "own-accts", autocomplete: "off" });
  const form = h("form", { class: "form-panel", onSubmit: onSubmit },
    h("div", { class: "sub-tabs", style: "margin:-6px 0 16px" },
      h("button", { class: "sub-tab on", type: "button" }, "Between my accounts"),
      h("button", { class: "sub-tab", type: "button", onClick: fakeLink }, "To someone else"),
      h("button", { class: "sub-tab", type: "button", onClick: fakeLink }, "Zilch®")),
    field("From", fromSel),
    field("To", toInput, "Any Bank of USA account number. Your own accounts are suggested; paste another to send to someone else."),
    h("datalist", { id: "own-accts" }, ...accounts.map((a) => h("option", { value: a.id }, a.nickname))),
    h("div", { class: "row" },
      field("Amount", h("input", { name: "amount", type: "number", min: "0.01", step: "0.01", required: true, placeholder: "$0.00" })),
      field("Frequency", h("select", { name: "frequency" }, h("option", {}, "One time"), h("option", { disabled: true }, "Weekly (coming never)")))),
    h("div", { class: "row" },
      field("Date", h("input", { name: "date", value: today(), readonly: true })),
      field("Memo", h("input", { name: "description", maxlength: 120, placeholder: "Optional" }))),
    err,
    h("div", { class: "form-actions" },
      h("button", { class: "btn btn-primary", type: "submit" }, "Make Transfer"),
      h("button", { class: "btn btn-ghost", type: "button", onClick: () => go("dashboard") }, "Cancel")),
    note("Transfers between Bank of USA accounts are immediate. Transfers to other banks take 1–3 business days, or a lifetime."));

  async function onSubmit(e) {
    e.preventDefault();
    const f = formData(form);
    await busy(form, err, async () => {
      await api().transfer({ fromId: f.from, toId: f.to.trim(), amount: f.amount, description: f.description });
      toast("Transfer sent");
      go("account", f.from);
    });
  }
  render(...formPage("transfer", "Transfer money", form, [
    h("section", { class: "panel side-panel" }, h("h3", {}, "Scheduled transfers"), h("p", {}, "You have no scheduled transfers. Your money is staying put, which is more than we can say for most people’s.")),
    h("section", { class: "panel side-panel" }, h("h3", {}, "Transfer limits"), h("p", {}, "Daily limit: your balance. Monthly limit: also your balance."), h("p", {}, "Need to move more? You’ll need more.")),
  ]));
}

async function depositView(preselect) {
  render(...shell("dashboard", spinner("Loading")));
  let accounts;
  try { accounts = await api().accounts(); } catch (e) { return render(...shell("dashboard", crumb(), alertBox(e.message))); }
  if (!accounts.length) return render(...shell("dashboard", crumb(), alertBox("Open an account first.", "info")));

  const err = h("div");
  const sel = h("select", { name: "account", required: true }, ...accounts.map(accountOption));
  if (preselect) sel.value = preselect;
  const form = h("form", { class: "form-panel", onSubmit: onSubmit },
    field("Deposit to", sel),
    h("div", { class: "row" },
      field("Amount", h("input", { name: "amount", type: "number", min: "0.01", step: "0.01", required: true, placeholder: "$0.00" })),
      field("Date", h("input", { name: "date", value: today(), readonly: true }))),
    field("Memo", h("input", { name: "description", maxlength: 120, placeholder: "e.g. Paycheck" })),
    err,
    h("div", { class: "form-actions" },
      h("button", { class: "btn btn-primary", type: "submit" }, "Make Deposit"),
      h("button", { class: "btn btn-ghost", type: "button", onClick: () => go("dashboard") }, "Cancel")),
    note("Endorse the back of the check, write “For Bank of USA deposit only”, and then imagine photographing it."));

  async function onSubmit(e) {
    e.preventDefault();
    const f = formData(form);
    await busy(form, err, async () => {
      await api().deposit({ accountId: f.account, amount: f.amount, description: f.description });
      toast("Deposit added");
      go("account", f.account);
    });
  }
  render(...formPage("dashboard", "Deposit a check", form, [
    h("section", { class: "panel side-panel" }, h("h3", {}, "Deposit limits"), h("p", {}, "Per check: $0 to infinity, inclusive."), h("p", {}, "Funds are generally available immediately, because they are made up.")),
  ]));
}

function openAccountView() {
  const err = h("div");
  const form = h("form", { class: "form-panel", onSubmit: onSubmit },
    field("Account type", h("select", { name: "type", required: true },
      h("option", { value: "Checking" }, "Advantage Checking (no advantages)"),
      h("option", { value: "Savings" }, "Advantage Savings (0.00% APY)"),
      h("option", { value: "Credit Card" }, "Customized No Rewards credit card"))),
    field("Nickname", h("input", { name: "nickname", required: true, maxlength: 60, placeholder: "e.g. Everyday checking" })),
    err,
    h("div", { class: "form-actions" },
      h("button", { class: "btn btn-primary", type: "submit" }, "Open account"),
      h("button", { class: "btn btn-ghost", type: "button", onClick: () => go("dashboard") }, "Cancel")),
    note("Opening takes about three seconds. Approval is guaranteed, which should worry you."));

  async function onSubmit(e) {
    e.preventDefault();
    const f = formData(form);
    await busy(form, err, async () => {
      const a = await api().openAccount({ type: f.type, nickname: f.nickname });
      toast("Account opened");
      go("account", a.id);
    });
  }
  render(...formPage("open", "Open an account", form, [
    h("section", { class: "panel side-panel" }, h("h3", {}, "What you’ll need"), h("p", {}, "A nickname. That’s it. Other banks ask for a Social Security number; we ask for vibes.")),
  ]));
}

// --- helpers & routing ----------------------------------------------------

const crumb = () => h("button", { class: "crumb", onClick: () => go("dashboard") }, "‹ Accounts Overview");
const retry = (fn) => h("button", { class: "btn btn-secondary", onClick: fn }, "Try again");

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
