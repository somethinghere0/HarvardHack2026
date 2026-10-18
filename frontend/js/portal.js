// Signed-in Online Banking chrome for Bank of USA: the navy utility header, the gray tab bar, the Activity Center
// sidebar and the small-print footer. Same rule as the homepage: the layout is played straight, the jokes are in
// the copy. All markup is createElement; the only innerHTML is for the static SVG icons below.

import { h } from "./ui.js";
import { logo } from "./landing.js";

const fakeLink = (e) => e.preventDefault();
const A = (text, cls, onClick) => h("a", { href: "#", class: cls, onClick: onClick || fakeLink }, text);

function svg(markup, cls) {
  const span = h("span", { class: cls || "ico", "aria-hidden": "true" });
  span.innerHTML = markup;
  return span;
}

const I = {
  search: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.8-3.8"/></svg>`,
  bell: `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 32V21a12 12 0 0 1 24 0v11l3 4H9l3-4ZM20 38a4 4 0 0 0 8 0"/></svg>`,
  billpay: `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2"><rect x="8" y="6" width="32" height="36" rx="2"/><path d="M15 15h18M15 22h18M15 29h10M30 34l3 3 6-7"/></svg>`,
  mail: `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="11" width="38" height="26" rx="2"/><path d="m5 13 19 14 19-14"/></svg>`,
  tag: `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6h17l19 19-17 17L6 23V6Z"/><circle cx="15" cy="15" r="3"/></svg>`,
  plus: `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="10" width="36" height="28" rx="2"/><path d="M6 18h36M24 24v10M19 29h10"/></svg>`,
  pie: `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2"><path d="M24 6a18 18 0 1 0 18 18H24V6Z"/><path d="M28 4a18 18 0 0 1 16 16H28V4Z"/></svg>`,
  check: `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="12" width="40" height="24" rx="2"/><path d="M10 20h12M10 26h8M30 30h8M30 24h8"/></svg>`,
  calendar: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="5" width="18" height="16" rx="1.5"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>`,
  pin: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 21s-6-6.2-6-11a6 6 0 0 1 12 0c0 4.8-6 11-6 11Z"/><circle cx="12" cy="10" r="2"/></svg>`,
  chevron: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 6 6 6-6 6"/></svg>`,
  down: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 4v12m0 0 5-5m-5 5-5-5M4 20h16"/></svg>`,
  info: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/></svg>`,
  flag: `<svg viewBox="0 0 70 40"><g transform="skewX(-30) translate(26 0)"><rect x="4" y="4" width="46" height="5.2" fill="#e31837"/><rect x="8" y="12" width="46" height="5.2" fill="#e31837"/><rect x="12" y="20" width="46" height="5.2" fill="#e31837"/><rect x="16" y="28" width="46" height="5.2" fill="#e31837"/><rect x="30" y="1" width="13" height="35" fill="#012169"/></g></svg>`,
  trend: `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M6 36 18 24l8 8 16-16M30 16h12v12"/></svg>`,
  zilch: `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M10 12h28L10 36h28"/></svg>`,
  lock: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="11" width="14" height="10" rx="1.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>`,
};
export const icons = I;
export { svg };

// --- header + tabs --------------------------------------------------------

export const TABS = [
  { label: "Accounts", route: "dashboard" },
  { label: "Bill Pay" },
  { label: "Transfer | Zilch®", route: "transfer" },
  { label: "Rewards & Deals" },
  { label: "Tools & Investing" },
  { label: "Security Center" },
  { label: "Open an Account", route: "open" },
  { label: "Help & Support" },
];

export function olbHeader({ badge, onHome, onLogout }) {
  const search = h("form", { class: "olb-search", role: "search", onSubmit: fakeLink },
    h("input", { type: "search", placeholder: "How can we help you?", "aria-label": "Help search" }),
    h("button", { type: "submit", "aria-label": "Search" }, svg(I.search)));
  return h("header", { class: "olb-head" }, h("div", { class: "olb-wrap olb-head-wrap" },
    h("div", { class: "olb-brand" }, logo(onHome), h("span", { class: "olb-product" }, "Online Banking")),
    h("div", { class: "olb-util" },
      badge,
      A("Profile & Settings", "olb-util-link"),
      h("span", { class: "olb-sep" }),
      A("Saved Items", "olb-util-link"),
      h("span", { class: "olb-sep" }),
      h("a", { href: "#", class: "olb-util-link olb-logout", onClick: (e) => { e.preventDefault(); onLogout(); } }, svg(I.lock, "ico ico-xs"), "Log Out"),
      search)));
}

export function olbTabs(active, go) {
  return h("nav", { class: "olb-tabs", "aria-label": "Online Banking" }, h("div", { class: "olb-wrap olb-tabs-wrap" },
    ...TABS.map((t) => h("a", {
      href: "#", class: `olb-tab ${t.route && t.route === active ? "on" : ""}`,
      onClick: (e) => { e.preventDefault(); if (t.route) go(t.route); },
    }, t.label))));
}

export function olbFooter() {
  return h("footer", { class: "olb-foot" }, h("div", { class: "olb-wrap" },
    h("div", { class: "olb-foot-links" },
      ...["Locations", "Contact Us", "Help & Support", "Accessible Banking", "Privacy", "Security",
        "Online Banking Service Agreement", "Advertising Practices", "Your Privacy Choices", "Site Map"]
        .map((t) => A(t, "olb-foot-link"))),
    h("p", {}, "Bank of USA, N.A. Member of nothing. Equal Housing Lender (we don’t lend). © 2026 Bank of USA Corporation. ",
      "Online Banking is available 24/7, except when it isn’t."),
    h("p", { class: "olb-foot-real" }, "Simulated bank for the Honeybank scam-detection honeypot. Not a real bank; no real money moves.")));
}

// --- dashboard pieces -----------------------------------------------------

export function promoStrip(icon, title, body, onClick) {
  return h("a", { href: "#", class: "promo-strip", onClick: onClick ? (e) => { e.preventDefault(); onClick(); } : fakeLink },
    h("span", { class: "promo-strip-copy" }, h("span", { class: "promo-strip-title" }, title), h("span", { class: "promo-strip-body" }, body)),
    svg(icon, "promo-strip-ico"));
}

export function activityCenter(go) {
  const tile = (icon, label, route) => h("a", {
    href: "#", class: "ac-tile", onClick: (e) => { e.preventDefault(); if (route) go(route); },
  }, svg(icon, "ac-ico"), h("span", {}, label));
  return h("aside", { class: "olb-side" },
    h("section", { class: "panel" },
      h("h2", { class: "panel-title" }, "Activity Center"),
      h("div", { class: "ac-grid" },
        tile(I.bell, "Alerts"), tile(I.billpay, "Bill Pay"), tile(I.mail, "Messages"),
        tile(I.tag, "Special Offers & Deals"), tile(I.plus, "Open an Account", "open"), tile(I.pie, "Spending & Budgeting"),
        tile(I.check, "Deposit a check", "deposit"), tile(I.zilch, "Zilch®", "transfer"), tile(I.trend, "Merely Edge®")),
      h("div", { class: "ac-links" },
        h("a", { href: "#", onClick: fakeLink }, svg(I.calendar, "ico ico-sm"), "Schedule an appointment"),
        h("a", { href: "#", onClick: fakeLink }, svg(I.pin, "ico ico-sm"), "Find us"))),
    h("a", { href: "#", class: "panel accordion", onClick: fakeLink }, svg(I.chevron, "ico ico-sm"), "Your Services"),
    h("section", { class: "panel ad" },
      h("h3", {}, "Did your credit score change?"),
      h("p", {}, "Probably. View your FIKO® Score for free and find out which direction."),
      A("View your FIKO® Score", "lnk"),
      h("p", { class: "ad-powered" }, "Powered by ", h("strong", {}, "dun & gone"))));
}

export function rewardsBlurb(sinceLabel) {
  return h("div", { class: "rewards-blurb" },
    h("div", { class: "rewards-badge" }, h("span", {}, "PREFERRED"), h("span", {}, "REGRETS"), h("small", {}, "PLYWOOD HONORS")),
    h("div", {}, h("p", {}, `You’ve been enjoying Preferred Regrets since ${sinceLabel}`), A("My summary", "lnk")));
}

// Bank-style empty row / notes
export const note = (text) => h("p", { class: "olb-note" }, svg(I.info, "ico ico-sm"), text);
