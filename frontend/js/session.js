// Session token from the auth proxy, plus which backend (live or demo) it belongs to.

const KEY = "hb.session";
const MODE_KEY = "hb.mode";

function read(k) {
  try { return localStorage.getItem(k); } catch { return null; }
}
function write(k, v) {
  try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* storage blocked */ }
}

export const session = {
  get() {
    try {
      const s = JSON.parse(read(KEY));
      if (!s?.token) return null;
      if (s.expires_at && new Date(s.expires_at) <= new Date()) { write(KEY, null); return null; }
      return s;
    } catch {
      return null;
    }
  },
  set(s) { write(KEY, JSON.stringify(s)); },
  update(patch) { const s = this.get(); if (s) this.set({ ...s, ...patch }); },
  clear() { write(KEY, null); },
};

// "live" talks to the auth proxy (and Nessie behind it); "demo" is an in-browser fake for working offline.
export function getMode() {
  return read(MODE_KEY) === "demo" ? "demo" : "live";
}
export function setMode(mode) {
  write(MODE_KEY, mode === "demo" ? "demo" : null);
}
