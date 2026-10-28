// Public homepage for Bank of USA: a pixel-faithful parody of a big retail bank's landing page.
// The layout is played completely straight; the jokes live in the copy and only reward people who read.
// Everything is built with createElement, and the only innerHTML is for static inline SVG icons defined here.

import { h } from "./ui.js";

const fakeLink = (e) => e.preventDefault();
const A = (text, cls, onClick) => h("a", { href: "#", class: cls, onClick: onClick || fakeLink }, text);

// Static SVG markup only (no user data) goes through here.
function svg(markup, cls) {
  const span = h("span", { class: cls || "ico", "aria-hidden": "true" });
  span.innerHTML = markup;
  return span;
}

// --- brand ----------------------------------------------------------------

// The "flagscape": slanted red stripes with a blue field. Drawn, not borrowed.
const FLAG = `<svg viewBox="0 0 70 40" xmlns="http://www.w3.org/2000/svg">
  <g transform="skewX(-30) translate(26 0)">
    <rect x="4"  y="4"  width="46" height="5.2" rx=".6" fill="#e31837"/>
    <rect x="8"  y="12" width="46" height="5.2" rx=".6" fill="#e31837"/>
    <rect x="12" y="20" width="46" height="5.2" rx=".6" fill="#e31837"/>
    <rect x="16" y="28" width="46" height="5.2" rx=".6" fill="#e31837"/>
    <rect x="30" y="1" width="13" height="35" fill="#012169"/>
    <rect x="43" y="1" width="3" height="35" fill="#fff" opacity=".85"/>
  </g>
</svg>`;

export function logo(onClick) {
  return h("a", { href: "#", class: "boa-logo", "aria-label": "Bank of USA home", onClick: (e) => { e.preventDefault(); onClick?.(); } },
    h("span", { class: "boa-wordmark" }, "BANK OF USA"), svg(FLAG, "boa-flag"));
}

// --- icons (line icons in link blue, like the real thing) -----------------

const I = {
  globe: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></svg>`,
  search: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.8-3.8"/></svg>`,
  chevron: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>`,
  dollar: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><path d="M12 6.5v11M14.8 9.2c-.4-1.2-1.5-1.7-2.8-1.7-1.6 0-2.9.8-2.9 2.1 0 2.9 5.9 1.4 5.9 4.4 0 1.4-1.4 2.2-3 2.2-1.6 0-2.8-.7-3.1-2"/></svg>`,
  card: `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="10" width="40" height="28" rx="3"/><path d="M4 18h40M10 30h8M22 30h6"/></svg>`,
  cash: `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="12" width="40" height="24" rx="2"/><circle cx="24" cy="24" r="6"/><path d="M10 18h.01M38 30h.01"/></svg>`,
  bell: `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 32V21a12 12 0 0 1 24 0v11l3 4H9l3-4ZM20 38a4 4 0 0 0 8 0"/></svg>`,
  bull: `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 14c4 2 7 2 10 0M40 14c-4 2-7 2-10 0M14 20c-2 6 0 12 4 16 2 2 4 3 6 3s4-1 6-3c4-4 6-10 4-16M18 20h12M19 26c1 2 3 3 5 3s4-1 5-3"/></svg>`,
  badge: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/></svg>`,
  piggy: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M5 11a7 7 0 0 1 13-2h2l1 3-2 1v3a2 2 0 0 1-2 2h-1l-1 2h-2l-1-2h-3l-1 2H6l-1-2.5A5 5 0 0 1 5 11Z"/><circle cx="15" cy="11" r=".6" fill="currentColor"/></svg>`,
  bank: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 9l9-5 9 5H3ZM5 9v8M10 9v8M14 9v8M19 9v8M3 20h18"/></svg>`,
  chat: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 5h16v11H9l-5 4V5Z"/></svg>`,
  calendar: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="5" width="18" height="16" rx="1.5"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>`,
  pin: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 21s-6-6.2-6-11a6 6 0 0 1 12 0c0 4.8-6 11-6 11Z"/><circle cx="12" cy="10" r="2"/></svg>`,
  phone: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2Z"/></svg>`,
  help: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7M12 17h.01"/></svg>`,
  house: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 11 12 4l9 7M5 10v10h14V10M10 20v-6h4v6"/></svg>`,
  close: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6 6 18"/></svg>`,
  wifi: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M7 9.5a5 5 0 0 1 0 5M10.5 7a9 9 0 0 1 0 10M14 4.5a13 13 0 0 1 0 15"/></svg>`,
  recycle: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m7 9 3-5 3 5M10 4v8M17 9l3 5h-6M20 14l-7-4M5 19h6l-3 5M11 19l-7 4"/></svg>`,
};

const social = {
  facebook: `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M14 8h3V4h-3c-2.8 0-4 1.8-4 4.2V11H7v4h3v7h4v-7h3l1-4h-4V8.6c0-.4.3-.6.6-.6Z"/></svg>`,
  instagram: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor"/></svg>`,
  linkedin: `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 9h4v12H4zM6 3a2 2 0 1 1 0 4 2 2 0 0 1 0-4ZM10 9h4v2c.6-1.2 2-2.3 4-2.3 3.4 0 4 2.2 4 5V21h-4v-6c0-1.6-.3-3-2-3s-2 1.4-2 3v6h-4V9Z"/></svg>`,
  x: `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 3h5l5 7 6-7h2l-7 8 8 10h-5l-5.5-7.4L5 21H3l7.4-8.5L3 3Z"/></svg>`,
  youtube: `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M22 8.2a3 3 0 0 0-2.1-2.1C18 5.6 12 5.6 12 5.6s-6 0-7.9.5A3 3 0 0 0 2 8.2 31 31 0 0 0 1.6 12 31 31 0 0 0 2 15.8a3 3 0 0 0 2.1 2.1c1.9.5 7.9.5 7.9.5s6 0 7.9-.5a3 3 0 0 0 2.1-2.1 31 31 0 0 0 .4-3.8 31 31 0 0 0-.4-3.8ZM10 15V9l5.2 3L10 15Z"/></svg>`,
};

// --- header ---------------------------------------------------------------

const UTIL_LEFT = ["Personal", "Wealth Mismanagement", "Business", "Corporations & Institutions"];
const UTIL_RIGHT = ["Security", "About Us", "En español", "Contact Us", "Help"];
const MAIN_NAV = ["Checking", "Savings & CDs", "Credit Cards", "Home Loans", "Auto Loans", "Merely Investing", "Worse Money Habits®"];

export function siteHeader({ badge, onBrand } = {}) {
  const fdic = h("div", { class: "fdic-bar" }, h("div", { class: "fdic-wrap" },
    h("span", { class: "fdic-pre" }, "Bank of USA deposit products:"),
    h("span", { class: "fdic-mark" }, "FDIC"),
    h("span", { class: "fdic-text" }, "Not FDIC-Insured · Backed by the full faith and credit of three undergrads")));

  const util = h("div", { class: "util-row" }, h("div", { class: "util-wrap" },
    h("nav", { class: "util-left", "aria-label": "Audience" },
      ...UTIL_LEFT.map((l, i) => A(l, i === 0 ? "util-link on" : "util-link"))),
    h("nav", { class: "util-right", "aria-label": "Utility" },
      ...UTIL_RIGHT.map((l) => l === "En español"
        ? h("a", { href: "#", class: "util-link", onClick: fakeLink }, svg(I.globe, "ico ico-sm"), l)
        : A(l, "util-link")),
      badge)));

  const search = h("form", { class: "site-search", role: "search", onSubmit: fakeLink },
    h("input", { type: "search", placeholder: "Search", "aria-label": "Search" }),
    h("button", { type: "submit", "aria-label": "Search" }, svg(I.search)));

  const mast = h("div", { class: "mast-row" }, h("div", { class: "mast-wrap" }, logo(onBrand), search));

  const nav = h("div", { class: "main-nav-row" }, h("nav", { class: "main-nav", "aria-label": "Products" },
    ...MAIN_NAV.map((l) => h("a", { href: "#", class: "main-nav-link", onClick: fakeLink }, l, svg(I.chevron, "ico ico-chev")))));

  return h("header", { class: "site-head" }, fdic, util, mast, nav);
}

// --- hero: sign-in + "choose the card" ------------------------------------

// CSS credit-card art. `network` is the little logo bottom-right.
function cardArt({ variant, banner, network }) {
  return h("div", { class: `cc cc-${variant}` },
    banner && h("div", { class: "cc-banner" }, banner),
    h("div", { class: "cc-chip" }),
    svg(I.wifi, "cc-wifi"),
    h("div", { class: "cc-brand" }, "BANK OF USA"),
    svg(I.recycle, "cc-recycle"),
    network === "vista"
      ? h("div", { class: "cc-net cc-vista" }, "VISTA", h("small", {}, "Signature"))
      : h("div", { class: "cc-net cc-mister" }, h("span", { class: "c1" }), h("span", { class: "c2" }), h("small", {}, "mistercard")));
}

const CARDS = [
  { amount: "$0", unit: "", label: "online bonus offer", fee: "No annual fee.", name: "Customized No Rewards",
    cta: ["0% choice category", "cash back offer"], variant: "red", network: "vista" },
  { amount: "$5", unit: "", label: "online bonus offer", fee: "No annual fee.", name: "No Rewards",
    cta: ["Unlimited 0%", "cash back on purchases"], variant: "silver", network: "vista", banner: "UNLIMITED-TIME OFFER" },
  { amount: "25", unit: "", label: "online bonus points offer", fee: "No annual fee.", name: "Travel Regrets",
    cta: ["1 point for every", "$1,000 spent on all purchases"], variant: "blue", network: "vista" },
  { amount: "0", unit: "%", label: "intro APR offer", fee: "No annual fee. Monthly fee.", name: "BankUSAcard®",
    cta: ["Intro APR offer", "for 0 billing cycles"], variant: "white", network: "mister" },
];

function cardColumn(c) {
  return h("div", { class: "offer" },
    h("div", { class: "offer-amt" },
      c.amount.startsWith("$") ? [h("sup", {}, "$"), c.amount.slice(1)] : c.amount,
      c.unit && h("sup", {}, c.unit)),
    h("div", { class: "offer-label" }, c.label),
    h("div", { class: "offer-fee" }, c.fee),
    cardArt(c),
    h("div", { class: "offer-name" }, c.name),
    h("a", { href: "#", class: "offer-cta", onClick: fakeLink }, c.cta[0], h("br"), c.cta[1]));
}

// `signin` is the functional sign-in card from app.js. `onOpen` goes to enrollment.
export function hero(signin, onOpen) {
  const left = h("div", { class: "hero-left" },
    signin,
    h("a", { href: "#", class: "open-acct", onClick: (e) => { e.preventDefault(); onOpen?.(); } },
      svg(I.dollar), "Open an account"));
  const right = h("div", { class: "hero-right" },
    h("h1", { class: "hero-title" }, "Choose the card that doesn't matter"),
    h("div", { class: "offers" }, ...CARDS.map(cardColumn)));
  return h("section", { class: "home-hero" }, h("div", { class: "hero-wrap" }, left, right));
}

// --- below the fold -------------------------------------------------------

function splitTiles() {
  const checking = h("div", { class: "split-tile tile-checking" },
    h("div", { class: "split-copy" },
      h("div", { class: "eyebrow" }, "NEW CHECKING CUSTOMERS"),
      h("h3", {}, "Cash offer up to $5"),
      h("p", {}, "Start by opening a new eligible checking account."),
      A("See details", "lnk")),
    h("div", { class: "split-art art-blue" },
      h("div", { class: "outline-amt" }, h("span", { class: "upto" }, "Up to"), h("span", { class: "big" }, "$5"), h("span", { class: "upto" }, "cash offer"))));

  const story = h("div", { class: "split-tile tile-story" },
    h("div", { class: "split-copy" },
      h("h3", { class: "quote" }, "“I’ve moved up from intern to senior intern”"),
      h("p", {}, "We asked teammates like Dana P., “What makes this company a great place to work?”"),
      A("Read their stories", "lnk")),
    h("div", { class: "split-art art-portrait" },
      svg(`<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
        <defs><linearGradient id="pbg" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="#e9eef6"/><stop offset="1" stop-color="#c9d4e6"/></linearGradient></defs>
        <rect width="200" height="200" fill="url(#pbg)"/>
        <circle cx="100" cy="78" r="36" fill="#f1d4c2"/>
        <path d="M64 70c0-30 72-30 72 0v8c-6-10-14-14-36-14s-30 4-36 14Z" fill="#6b4a3a"/>
        <path d="M30 200c0-40 30-62 70-62s70 22 70 62Z" fill="#012169"/>
        <path d="M92 138h16l-8 22Z" fill="#fff"/>
      </svg>`, "portrait")));

  return h("section", { class: "split" }, h("div", { class: "wrap-x split-grid" }, checking, story));
}

function features() {
  const feat = (icon, title, body, cta, brand) => h("div", { class: "feat" },
    brand
      ? h("div", { class: "merely" }, h("span", { class: "merely-word" }, "MERELY"), svg(I.bull, "merely-bull"),
          h("span", { class: "merely-sub" }, "A BANK OF USA COMPANY"))
      : svg(icon, "feat-ico"),
    h("h3", {}, title), h("p", {}, body), A(cta, "lnk"));
  return h("section", { class: "features" }, h("div", { class: "wrap-x feat-grid" },
    feat(I.card, "0% customized cash back offer",
      "Earn no cash back in the category of your choice with the Customized No Rewards credit card.", "Apply now"),
    feat(I.cash, "Cash offer up to $5", "Check out this offer for new checking customers. It’s five dollars.", "See details"),
    feat(I.bell, "Custom mobile alerts",
      "With our Mobile Banking app alerts, get notified every time nothing happens to your money.", "Get the app"),
    feat(null, "Invest the way you want",
      "Choose your own investments, set your goals online, or talk with an advisor who is also guessing.", "Get started", true)));
}

const ARTICLES = [
  { icon: I.badge, text: "6 essential questions to ask before choosing a bank with no rewards program", tone: "a" },
  { icon: I.piggy, text: "What is a Checking Account? A new way to check on your money", tone: "b" },
  { icon: I.bank, text: "Savings accounts and shoeboxes: Which should I choose?", tone: "c" },
  { icon: I.chat, text: "Money Confessions ‐ real people share where their money went", tone: "d" },
];

function goals() {
  return h("section", { class: "goals" }, h("div", { class: "wrap-x" },
    h("h2", { class: "sec-title" }, "Your financial goals matter"),
    h("p", { class: "sec-lede" }, "We can help you achieve them through Worse Money Habits® financial education and programs that make communities slightly stronger."),
    h("div", { class: "articles" }, ...ARTICLES.map((a) =>
      h("a", { href: "#", class: `article tone-${a.tone}`, onClick: fakeLink },
        h("span", { class: "article-card" }, svg(a.icon, "ico ico-blue"), h("span", {}, a.text))))),
    h("p", { class: "sec-sub" }, "Explore more topics and build your financial know-how. Or don’t."),
    h("div", { class: "center" }, h("a", { href: "#", class: "pill pill-navy", onClick: fakeLink }, "Visit Worse Money Habits®"))));
}

function phone(cls, ...screen) {
  return h("div", { class: `phone ${cls}` }, h("div", { class: "phone-notch" }), h("div", { class: "phone-screen" }, ...screen));
}

function news() {
  const gauge = svg(`<svg viewBox="0 0 120 70" xmlns="http://www.w3.org/2000/svg">
    <path d="M10 65A50 50 0 0 1 110 65" fill="none" stroke="#e3e7ee" stroke-width="10" stroke-linecap="round"/>
    <path d="M10 65A50 50 0 0 1 60 15" fill="none" stroke="#e31837" stroke-width="10" stroke-linecap="round"/>
    <path d="M60 15A50 50 0 0 1 96 30" fill="none" stroke="#f0a500" stroke-width="10" stroke-linecap="round"/>
    <circle cx="60" cy="65" r="4" fill="#012169"/><path d="M60 65 92 34" stroke="#012169" stroke-width="3" stroke-linecap="round"/>
  </svg>`, "gauge");
  return h("section", { class: "news" }, h("div", { class: "wrap-x" },
    h("h2", { class: "sec-title" }, "Your news and information"),
    h("div", { class: "news-grid" },
      h("div", { class: "news-copy" },
        h("h3", {}, "Level up your account security"),
        h("p", {}, "Watch your security meter rise as you ignore every email that says it’s from us. See it in the Security Center in Mobile and Online Banking."),
        h("a", { href: "#", class: "pill pill-maroon", onClick: fakeLink }, "Check your level")),
      phone("phone-light",
        h("div", { class: "ps-bar" }, "Security Center"),
        h("div", { class: "ps-eyebrow" }, "MANAGE YOUR SECURITY PREFERENCES"),
        gauge,
        h("div", { class: "ps-title" }, "Suspicious security"),
        h("div", { class: "ps-sub" }, "0 of 5 features: High"),
        h("div", { class: "ps-row" }, "Strengthen your password"),
        h("div", { class: "ps-row" }, "Stop clicking links"),
        h("div", { class: "ps-row" }, "We will never email you. Ever.")))));
}

function appBand() {
  const row = (label, amt) => h("div", { class: "ps-acct" }, h("span", {}, label), h("strong", {}, amt));
  return h("section", { class: "app-band" }, h("div", { class: "wrap-x app-grid" },
    h("div", { class: "app-copy" },
      h("h2", {}, "Convenient banking with our Mobile app"),
      h("a", { href: "#", class: "pill pill-white", onClick: fakeLink }, "Explore our app")),
    phone("phone-dark",
      h("div", { class: "ps-tabs" }, h("span", {}, "Accounts"), h("span", { class: "on" }, "Dashboard")),
      h("div", { class: "ps-eyebrow" }, "SELECT YOUR DASHBOARD"),
      h("div", { class: "ps-brand" }, "BANK OF USA"),
      row("My Checking", "$4.00"), row("No Rewards card", "$2,543.21 owed"), row("Savings", "$0.37"),
      h("div", { class: "ps-foot" }, "Available balance, technically"))));
}

function connect() {
  const item = (icon, label) => h("a", { href: "#", class: "connect-card", onClick: fakeLink }, svg(icon, "ico ico-blue"), label);
  return h("section", { class: "connect" }, h("div", { class: "wrap-x" },
    h("h2", { class: "sec-title" }, "Connect with us"),
    h("div", { class: "connect-grid" },
      item(I.calendar, "Schedule an appointment"), item(I.pin, "Find a location (there is one)"),
      item(I.phone, "Contact us"), item(I.help, "Help center"))));
}

const NOTS = ["Are Not FDIC Insured", "Are Not Bank Guaranteed", "May Lose Value",
  "Are Not Deposits", "Are Not Insured by Any Federal Government Agency", "Are Not Real"];

function disclosures() {
  return h("section", { class: "disclose" }, h("div", { class: "wrap-x" },
    h("p", { class: "disclose-pre" }, "Investment and insurance products:"),
    h("div", { class: "nots" }, ...NOTS.map((t) => h("div", { class: "not" }, t))),
    A("Online Banking Service Agreement", "lnk small"),
    h("p", {}, "Investing in securities involves risks, and there is always the potential of losing money when you invest in securities. There is also the potential of losing money when you don’t. You should review any planned financial transactions that may have tax or legal implications with your personal tax or legal advisor, if you have one."),
    h("p", {}, "Securities products are provided by Merely Lynch, Pierce, Fenner & Smith Incorporated (also referred to as “MLPF&S”, or “Merely”), a registered broker-dealer, registered investment adviser, Member SIPC-ish, and a wholly-owned subsidiary of Bank of USA Corporation. MLPF&S makes available certain investment products sponsored, managed, distributed or provided by companies that are affiliates of Bank of USA Corporation, of which there are zero."),
    h("p", {}, "Bank of USA Private Bank is a division of Bank of USA, N.A. (Not Actually), and a wholly owned subsidiary of Bank of USA Corporation. Trust and fiduciary services are provided by Bank of USA, N.A. and the U.S. Trust-Us Company of Delaware. Both are indirect subsidiaries of a hackathon."),
    h("p", {}, "Banking, credit card, automobile loans, mortgage and home equity products are provided by Bank of USA, N.A. and affiliated banks, Members FDIC and wholly owned subsidiaries of Bank of USA Corporation. Credit and collateral are subject to approval. Terms and conditions apply. This is not a commitment to lend. This is not a commitment to anything. Programs, rates, terms and conditions are subject to change without notice, and have."),
    h("p", { class: "disclose-real" }, "Bank of USA is a simulated bank built for Honeybank, a scam-detection honeypot. It is not a real bank; no real money moves. Any resemblance to an actual bank is the point.")));
}

export function homepage(signin, { onOpen } = {}) {
  return [hero(signin, onOpen), splitTiles(), features(), goals(), news(), appBand(), connect(), disclosures()];
}

// --- footer ---------------------------------------------------------------

const FOOT_1 = ["Locations", "Contact Us", "Help & Support", "Browse with Specialist", "Accessible Banking", "Privacy",
  "Children’s Privacy", "Security", "Online Banking Service Agreement", "AdChoices"];
const FOOT_2 = ["Your Privacy Choices", "Site Map", "Careers", "Share Your Feedback", "View Full Online Banking Site"];

export function siteFooter() {
  const row = (items, cls) => h("div", { class: `foot-row ${cls || ""}` }, ...items.map((t) => A(t, "foot-link")));
  return h("footer", { class: "site-foot" }, h("div", { class: "wrap-x" },
    row(FOOT_1), row(FOOT_2, "foot-row-2"),
    h("div", { class: "foot-connect" }, "Connect with us"),
    h("div", { class: "socials" }, ...Object.entries(social).map(([k, m]) =>
      h("a", { href: "#", class: "social", "aria-label": k, onClick: fakeLink }, svg(m)))),
    h("p", { class: "foot-legal" }, "Bank of USA, N.A. Member of nothing. ",
      h("span", { class: "ehl" }, "Equal Housing Lender", svg(I.house, "ico ico-sm")), " (we don’t lend)."),
    h("p", { class: "foot-legal" }, "© 2026 Bank of USA Corporation. All rights reserved. Some wrongs reserved too."),
    h("p", { class: "foot-legal" }, A("Patent: pending.bankofusa.com", "foot-link"))));
}

// --- sticky bits ----------------------------------------------------------

const dismissed = (k) => { try { return sessionStorage.getItem(k) === "1"; } catch { return false; } };
const dismiss = (k, el) => { try { sessionStorage.setItem(k, "1"); } catch { /* ignore */ } el.remove(); };

export function promoBanner() {
  if (dismissed("hb.promo")) return null;
  const el = h("div", { class: "promo", role: "status" }, h("div", { class: "wrap-x promo-wrap" },
    svg(I.card, "ico ico-red"),
    h("span", {}, "Earn no cash rewards plus a $0 limited-time online bonus offer. ", A("See offer now", "lnk")),
    h("button", { class: "promo-x", "aria-label": "Close", onClick: () => dismiss("hb.promo", el) }, svg(I.close))));
  return el;
}

export function cookieBanner() {
  if (dismissed("hb.cookie")) return null;
  const el = h("div", { class: "cookie", role: "dialog", "aria-label": "Cookie notice" },
    h("p", {}, "We use cookies and other tracking technologies to collect data for advertising, fraud prevention, analytics, and remembering that you were here. By using this website, you agree that this is a website. ", A("Privacy Notices", "lnk")),
    h("button", { class: "promo-x", "aria-label": "Close", onClick: () => dismiss("hb.cookie", el) }, svg(I.close)));
  return el;
}
