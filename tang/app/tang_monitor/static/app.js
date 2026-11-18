"use strict";
// All server-provided strings are inserted with textContent (via h()), never innerHTML.
const POLL_MS = 10000;  // only while the live connection is down
const HISTORY_SHORT = 10;
let historyAll = false;  // "Show all" in History
const openDetails = new Set();
let lastState = null;
let lastText = null;
let pendingForget = null;  // device id awaiting the inline "Forget? Yes / Cancel" confirmation
let forgetNote = null;
// Reservation banner state lives at module level so a re-render from a state update can't cut the
// confirmation short or bring the yellow banner back.
let reserveSaving = false;
let reserveError = null;
let reserveConfirm = null;  // null | "shown" | "fading"
const CONFIRM_MS = 4000;
const FADE_MS = 1000;

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function details(id, title, ...kids) {
  const d = h("details", {}, h("summary", {}, title), ...kids);
  d.dataset.id = id;
  if (openDetails.has(id)) d.open = true;
  d.addEventListener("toggle", () => {
    if (d.open) openDetails.add(id); else openDetails.delete(id);
  });
  return d;
}

function fmtTime(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const now = new Date();
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === now.toDateString()) return "today " + time;
  if (d.toDateString() === y.toDateString()) return "yesterday " + time;
  return d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + time;
}

function result(r) {
  if (r.kind === "adv" && r.status === 200) return "fetched keys";
  if (r.kind === "rec" && r.status === 200) return "unlock request answered";
  return "error";
}

function fallbackCopy(pre) {
  const range = document.createRange();
  range.selectNodeContents(pre);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  try { return document.execCommand("copy"); } catch (e) { return false; }
}

function copyBtn(text, pre) {
  const b = h("button", { type: "button" }, "Copy");
  b.addEventListener("click", async () => {
    let ok = false;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try { await navigator.clipboard.writeText(text); ok = true; } catch (e) { ok = false; }
    }
    if (!ok) ok = fallbackCopy(pre);
    b.textContent = ok ? "Copied" : "Copy failed";
    setTimeout(() => { b.textContent = "Copy"; }, 1500);
  });
  return b;
}

function cmd(text) {
  const pre = h("pre", {}, text);
  return h("div", { class: "cmd" }, pre, copyBtn(text, pre));
}

// A numbered step: "n. text" and its command.
function step(n, s) {
  return h("div", {}, h("p", {}, n + ". " + s.text), cmd(s.command));
}

const STEP_BY_STEP_WHY = "Works on the one binding you pick, instead of every binding to this Tang server, " +
  "using short commands you can read before running them with sudo.";

const EDIT_NOTE = "Fixing may print \u201cNo key available with this passphrase.\u201d before " +
  "\u201cBinding edited successfully\u201d. That line is normal: Clevis first checks for an empty password, " +
  "then unlocks with the existing binding.";

const TEST_NOTE = "The test proves this machine can fetch its key from the new address. " +
  "It does not prove the boot-time network works; only restarting the machine does.";

function fixDetails(dev, c) {
  const id = "fix:" + dev.device;
  return details(id, "How to fix",
    h("p", {}, "Run this on ", h("code", {}, dev.device), ". It finds every binding to this Tang server on " +
      "that machine, points it at the current address, and tests it: OK means the device got its key from here."),
    cmd(c.one_step_fix), h("p", { class: "muted" }, EDIT_NOTE), h("p", { class: "muted" }, TEST_NOTE),
    details(id + ":steps", "Step by step instead",
      h("p", { class: "muted" }, STEP_BY_STEP_WHY),
      step(1, c.find[0]), step(2, c.find[1]),
      step(3, { text: "Point the binding at this Home Assistant machine.", command: c.fix }),
      h("p", { class: "muted" }, EDIT_NOTE),
      step(4, { text: "Test it. It prints OK when the device gets its key from here.", command: c.test })));
}

async function post(path) {
  try {
    const r = await fetch(path, { method: "POST" });
    if (!r.ok && r.status !== 404 && r.status !== 409) alert("Request failed: " + r.status);
  } catch (e) {
    alert("Request failed: " + e);
  }
  refresh();
}

async function forgetDevice(device) {
  pendingForget = null;
  try {
    const r = await fetch("api/devices/" + encodeURIComponent(device) + "/forget", { method: "POST" });
    if (r.ok) {
      const j = await r.json();
      forgetNote = j.still_known_via_options ? device : null;
      if (!j.forgot) lastText = null;
    } else if (r.status !== 404) {
      alert("Request failed: " + r.status);
    }
  } catch (e) {
    alert("Request failed: " + e);
  }
  lastText = null;
  refresh();
}

function renderStatus(s) {
  const last = s.requests.find(r => r.kind === "rec" && r.status === 200);
  return h("div", { class: "card status" },
    h("span", { class: s.running ? "up" : "down" }, s.running ? "● Running" : "● Not answering"),
    h("span", {}, "Last unlock: ", last ? last.device + ", " + fmtTime(last.at) : "none yet"),
    h("span", {}, s.keys.length + (s.keys.length === 1 ? " key" : " keys")));
}

async function markReserved() {
  reserveSaving = true;
  reserveError = null;
  render(lastState);
  try {
    const r = await fetch("api/address-reserved", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reserved: true }) });
    if (r.ok) {
      reserveSaving = false;
      reserveConfirm = "shown";
      lastState = { ...lastState, address_reserved: true };
      lastText = null;
      render(lastState);
      setTimeout(startFade, CONFIRM_MS);
      refresh();
      return;
    }
    let msg = "Request failed: " + r.status;
    try { const j = await r.json(); if (j && j.error) msg = j.error; } catch (e) { /* keep status text */ }
    reserveError = msg;
  } catch (e) {
    reserveError = "Request failed: " + e;
  }
  reserveSaving = false;
  render(lastState);
}

function startFade() {
  reserveConfirm = "fading";
  const el = document.querySelector(".banner.ok");
  if (el) el.classList.add("fade");
  setTimeout(() => { reserveConfirm = null; render(lastState); }, FADE_MS);
}

// How to pick this machine out of the router's device list: the MAC is certain; the name is what it sends the
// router over DHCP, which routers usually show unless someone renamed the device there.
function findPiHint(s) {
  const mac = s.pi_mac && h("code", {}, s.pi_mac);
  const name = s.pi_hostname && h("code", {}, s.pi_hostname);
  if (mac && name) return ["In your router's device list, it's the one with MAC address ", mac,
    ", probably named ", name, "."];
  if (mac) return ["In your router's device list, it's the one with MAC address ", mac, "."];
  return ["In your router's device list, it's probably named ", name, "."];
}

// Every banner uses this layout: paragraphs on the left and actions on the right, vertically centered; on
// narrow windows the actions become full width under the text (style.css). `below` spans the full width
// underneath (e.g. "How to fix"). kind: "warn" | "bad" | "ok". A paragraph is a string, an array of parts,
// or a ready-made element.
// address:port as a person would type it ([v6]:port); just the address when the port is unknown.
function endpoint(addr, port) {
  if (port == null) return addr;
  return (addr.includes(":") ? "[" + addr + "]" : addr) + ":" + port;
}

function banner(kind, paras, actions, ...below) {
  const acts = (actions || []).filter(Boolean);
  const ps = paras.filter(Boolean).map(p => p instanceof Node ? p : h("p", {}, p));
  return h("div", { class: "banner " + kind },
    h("div", { class: "side" },
      h("div", { class: "text" }, ...ps),
      acts.length > 0 && h("div", { class: "actions" }, ...acts)),
    ...below);
}

function renderBanner(s) {
  if (reserveConfirm) {
    return banner("ok" + (reserveConfirm === "fading" ? " fade" : ""),
      ["✓ Address marked as reserved. You can change this anytime in this app's Configuration."]);
  }
  if (s.address_reserved) return null;
  const addr = s.primary_address;
  return banner("warn", [
    [...(addr ? ["Reserve ", h("code", {}, addr), " for this Home Assistant machine"]
      : ["Reserve this Home Assistant machine's address"]),
     " in your router's DHCP settings (often called a DHCP reservation or static lease), then press " +
     "“Mark as reserved”."],
    (s.pi_mac || s.pi_hostname) && findPiHint(s),
    reserveError && h("p", { class: "err" }, reserveError + " You can also turn on Address reserved in this " +
      "app's Configuration."),
  ], [
    h("button", reserveSaving ? { type: "button", disabled: "", onclick: markReserved }
      : { type: "button", onclick: markReserved }, "Mark as reserved"),
    reserveSaving && h("span", {}, "Saving…"),
  ]);
}

function renderAlerts(s) {
  return s.devices.filter(d => d.flag !== "none").map(d => {
    const tangAt = s.primary_address ? h("code", {}, endpoint(s.primary_address, s.port)) : "a different address";
    const dev = h("code", {}, d.device);
    const line = d.flag === "fixed_untested"
      ? ["Marked fixed, not yet tested. Run the test below, or restart ", dev, "."]
      : [dev, " unlocks via ", h("code", {}, endpoint(d.last_ok_address, d.last_ok_port)), ", but Tang is now at ",
        tangAt,
        ". It will show the password prompt at boot until this is fixed."];
    const fixedBtn = d.flag === "flagged" && h("button", { type: "button",
      onclick: () => post("api/devices/" + encodeURIComponent(d.device) + "/fixed") }, "I've fixed it");
    return banner("bad", [line], [fixedBtn], d.commands && fixDetails(d, d.commands));
  });
}

function renderHistory(s) {
  const shown = historyAll ? s.requests : s.requests.slice(0, HISTORY_SHORT);
  const more = s.requests.length > HISTORY_SHORT && h("p", {},
    h("button", { type: "button", onclick: () => { historyAll = !historyAll; render(lastState); } },
      historyAll ? "Show fewer" : "Show all"));
  const rows = shown.map(r => h("tr", { class: r.known ? "" : "unknown" },
    h("td", {}, fmtTime(r.at)),
    h("td", {}, r.device, !r.known && h("span", { class: "tag" }, " ⚠ unknown"),
      !r.known && h("button", { type: "button", class: "small",
        onclick: () => post("api/devices/" + encodeURIComponent(r.device) + "/known") }, "Mark as known")),
    h("td", { class: "mono" }, r.ip),
    h("td", { class: result(r) === "error" ? "err" : "" }, result(r))));
  return [h("h2", {}, "History"), h("div", { class: "scroll" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "When"), h("th", {}, "Who"), h("th", {}, "IP"), h("th", {}, "Result"))),
    h("tbody", {}, rows.length ? rows : h("tr", {}, h("td", { colspan: 4, class: "muted" }, "No requests yet."))))),
    more];
}

function renderKeys(s) {
  return [h("h2", {}, "Keys"), h("div", { class: "card" },
    s.keys.length ? s.keys.map(k => h("div", {}, k.use + ": ", h("code", {}, k.s256)))
      : h("span", { class: "muted" }, "No keys."))];
}

function forgetControl(device) {
  if (pendingForget === device) {
    return h("span", {}, "Forget? ",
      h("button", { type: "button", onclick: () => forgetDevice(device) }, "Yes"), " ",
      h("button", { type: "button", onclick: () => { pendingForget = null; render(lastState); } }, "Cancel"));
  }
  return h("button", { type: "button", onclick: () => { pendingForget = device; render(lastState); } }, "Forget");
}

function renderDevices(s) {
  const rows = s.devices.map(d => ({ device: d.device, rec: d }));
  const norm = d => d.trim().toLowerCase().replace(/\.+$/, "");
  const seen = new Set(rows.map(r => norm(r.device)));
  for (const k of s.known_devices || []) {
    if (!seen.has(norm(k.device))) { seen.add(norm(k.device)); rows.push({ device: k.device, rec: null }); }
  }
  const body = rows.length ? rows.map(({ device, rec }) => h("div", { class: "cmd" },
    h("div", { style: "flex:1" },
      h("strong", {}, device),
      rec ? [...(rec.last_ip ? [" (", h("code", {}, rec.last_ip), ")"] : []),
        " · reaches Tang at ", h("code", {}, endpoint(rec.last_ok_address, rec.last_ok_port)),
        " · last seen " + fmtTime(rec.last_ok_at) +
        " · " + (rec.flag === "none" ? "OK" : rec.flag === "flagged" ? "needs fixing" : "fixed, not yet tested")]
        : " · known, not seen yet"),
    forgetControl(device)))
    : h("span", { class: "muted" }, "No devices tracked yet.");
  const note = forgetNote && h("p", { class: "muted" }, forgetNote +
    " is also listed in this app's Configuration (Known devices). Remove it there to stop treating it as known.");
  return [h("h2", {}, "Devices"), h("div", { class: "card" }, body, note)];
}

function renderAddDevice(s) {
  const t = s.test_commands;
  if (!t) return null;
  const id = "add";  // remembers whether it is open across re-renders
  const sec = h("details", { class: "section" }, h("summary", {}, h("h2", {}, "Add a Linux device")),
    h("div", { class: "card" },
      h("p", {}, "For a Linux machine whose disk is encrypted with LUKS2. Once set up, it unlocks at boot by " +
        "asking this Tang server, and its password still works whenever Tang can't be reached."),
      !s.address_reserved && h("p", { class: "err" }, "Reserve this Home Assistant machine's address first " +
        "(see the banner above). The binding stores the address."),
      h("p", {}, "1. Install Clevis on the device. Debian or Ubuntu: ",
        h("code", {}, "clevis clevis-luks clevis-initramfs"), ". Fedora: ",
        h("code", {}, "clevis clevis-luks clevis-dracut"), ". Arch: ", h("code", {}, "clevis"),
        " plus a boot hook (see this app's Documentation tab)."),
      step(2, t.find[0]),
      t.bind ? step(3, { text: "Bind the disk to this Tang server. It asks for the disk's password.",
                         command: t.bind })
        : h("p", {}, "3. Bind the disk. (The command appears once this machine's address is known.)"),
      h("p", {}, "4. Make sure the device's boot image includes Clevis and its network. This depends on the " +
        "distribution: see this app's Documentation tab."),
      step(5, t.find[1]),
      step(6, { text: "Test it. It prints OK when the device gets its key from here, and changes nothing.",
                command: t.test }),
      h("p", {}, "7. Restart the device. It should unlock without asking for the password.")));
  sec.dataset.id = id;
  if (openDetails.has(id)) sec.open = true;
  sec.addEventListener("toggle", () => { if (sec.open) openDetails.add(id); else openDetails.delete(id); });
  return sec;
}

function render(s) {
  const app = document.getElementById("app");
  // History goes last: "Show all" can make it very long.
  app.replaceChildren(...[renderStatus(s), renderBanner(s), renderAlerts(s), renderKeys(s), renderDevices(s),
    renderAddDevice(s), renderHistory(s)].flat().filter(Boolean));
}

// Apply a state snapshot (JSON text). Held back while the user is selecting text on the page, so a re-render
// doesn't wipe out what they're copying; applied when the selection ends.
let pendingText = null;

function selecting() {
  const sel = window.getSelection();
  const app = document.getElementById("app");
  return sel && !sel.isCollapsed && sel.anchorNode && app.contains(sel.anchorNode);
}

function apply(text) {
  if (selecting()) { pendingText = text; return; }
  pendingText = null;
  if (text === lastText) return;
  lastText = text;
  lastState = JSON.parse(text);
  // Don't rebuild the banner mid-fade (a new element would jump to transparent); the fade's end timer re-renders.
  if (reserveConfirm !== "fading") render(lastState);
}

document.addEventListener("selectionchange", () => {
  if (pendingText !== null && !selecting()) apply(pendingText);
});

async function refresh() {
  try {
    const r = await fetch("api/state");
    if (!r.ok) throw new Error("HTTP " + r.status);
    apply(await r.text());
  } catch (e) {
    const app = document.getElementById("app");
    if (!lastState) app.replaceChildren(h("p", { class: "err" }, "Could not load state: " + e));
  }
}

// Live updates: the server pushes the state when it changes. While the connection is down, poll and retry.
let socket = null;
let pollTimer = null;
let retryTimer = null;
let retryMs = 1000;

function startPolling() {
  if (!pollTimer) pollTimer = setInterval(refresh, POLL_MS);
}

function connect() {
  clearTimeout(retryTimer);
  retryTimer = null;
  if (socket || !window.WebSocket) { if (!window.WebSocket) startPolling(); return; }
  const url = new URL("api/ws", location.href);
  url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
  let ws;
  try { ws = new WebSocket(url); } catch (e) { startPolling(); return; }
  socket = ws;
  startPolling();  // until it opens; a connection can hang while connecting
  ws.onopen = () => {
    retryMs = 1000;
    clearInterval(pollTimer);
    pollTimer = null;
  };
  ws.onmessage = ev => apply(ev.data);
  ws.onclose = () => {
    if (socket !== ws) return;
    socket = null;
    startPolling();
    refresh();
    retryTimer = setTimeout(connect, retryMs);
    retryMs = Math.min(retryMs * 2, 30000);
  };
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && !socket) { retryMs = 1000; connect(); refresh(); }
});

refresh();
connect();
