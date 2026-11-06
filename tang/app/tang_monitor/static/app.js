"use strict";
// All server-provided strings are inserted with textContent (via h()), never innerHTML.
const POLL_MS = 10000;
const openDetails = new Set();
let lastState = null;
let lastText = null;
let pendingForget = null;  // device id awaiting the inline "Forget? Yes / Cancel" confirmation
let forgetNote = null;
// Reservation banner state lives at module level so the 10-second poll's re-render can't cut the
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

function findSteps(steps) {
  return steps.map((s, i) => h("div", {}, h("p", {}, (i + 1) + ". " + s.text), cmd(s.command)));
}

function oneStep(idPrefix, c, withFix) {
  return details(idPrefix + ":onestep", "Can't tell which binding is the right one?",
    h("p", { class: "muted" },
      "This script finds every binding to this Tang server on this machine and acts on each one."),
    withFix && h("p", {}, "Fix everything it finds:"), withFix && cmd(c.one_step_fix),
    h("p", {}, "Test everything it finds:"), cmd(c.one_step_test));
}

const TEST_NOTE = "The test proves this machine can fetch its key from the new address. " +
  "It does not prove the boot-time network works; only restarting the machine does.";

function fixDetails(dev, c) {
  return details("fix:" + dev.device, "How to fix",
    h("p", {}, "1. Find the disk and binding slot."), findSteps(c.find),
    h("p", {}, "2. Point the binding at this Home Assistant machine."), cmd(c.fix),
    h("p", {}, "3. Test it."), cmd(c.test), h("p", { class: "muted" }, TEST_NOTE),
    oneStep("fix:" + dev.device, c, true));
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
    const piAddr = s.primary_address ? h("code", {}, s.primary_address) : "a different address";
    const dev = h("code", {}, d.device);
    const line = d.flag === "fixed_untested"
      ? ["Marked fixed, not yet tested. Run the test below, or restart ", dev, "."]
      : [dev, " unlocks via ", h("code", {}, d.last_ok_address), ", but Home Assistant is now at ", piAddr,
        ". It will show the password prompt at boot until this is fixed."];
    const fixedBtn = d.flag === "flagged" && h("button", { type: "button",
      onclick: () => post("api/devices/" + encodeURIComponent(d.device) + "/fixed") }, "I've fixed it");
    return banner("bad", [line], [fixedBtn], d.commands && fixDetails(d, d.commands));
  });
}

function renderHistory(s) {
  const rows = s.requests.map(r => h("tr", { class: r.known ? "" : "unknown" },
    h("td", {}, fmtTime(r.at)),
    h("td", {}, r.device, !r.known && h("span", { class: "tag" }, " ⚠ unknown"),
      !r.known && h("button", { type: "button", class: "small",
        onclick: () => post("api/devices/" + encodeURIComponent(r.device) + "/known") }, "Mark as known")),
    h("td", { class: "mono" }, r.ip),
    h("td", { class: result(r) === "error" ? "err" : "" }, result(r))));
  return [h("h2", {}, "History"), h("div", { class: "scroll" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "When"), h("th", {}, "Who"), h("th", {}, "IP"), h("th", {}, "Result"))),
    h("tbody", {}, rows.length ? rows : h("tr", {}, h("td", { colspan: 4, class: "muted" }, "No requests yet."))))) ];
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
        " · reaches Tang at ", h("code", {}, rec.last_ok_address),
        " · last seen " + fmtTime(rec.last_ok_at) +
        " · " + (rec.flag === "none" ? "OK" : rec.flag === "flagged" ? "needs fixing" : "fixed, not yet tested")]
        : " · known, not seen yet"),
    forgetControl(device)))
    : h("span", { class: "muted" }, "No devices tracked yet.");
  const note = forgetNote && h("p", { class: "muted" }, forgetNote +
    " is also listed in this app's Configuration (Known devices). Remove it there to stop treating it as known.");
  return [h("h2", {}, "Devices"), h("div", { class: "card" }, body, note)];
}

function renderTestCommands(s) {
  const t = s.test_commands;
  if (!t) return null;
  return [h("h2", {}, "Test a newly bound device"), h("div", { class: "card" },
    details("test:new", "How to test",
      h("p", {}, "1. Find the disk and binding slot."), findSteps(t.find),
      h("p", {}, "2. Test it."), cmd(t.test), h("p", { class: "muted" }, TEST_NOTE),
      details("test:new:onestep", "Can't tell which binding is the right one?",
        cmd(t.one_step_test))))];
}

function render(s) {
  const app = document.getElementById("app");
  app.replaceChildren(...[renderStatus(s), renderBanner(s), renderAlerts(s), renderHistory(s),
    renderKeys(s), renderDevices(s), renderTestCommands(s)].flat().filter(Boolean));
}

async function refresh() {
  try {
    const r = await fetch("api/state");
    if (!r.ok) throw new Error("HTTP " + r.status);
    const text = await r.text();
    const sel = window.getSelection();
    const app = document.getElementById("app");
    const selecting = sel && !sel.isCollapsed && sel.anchorNode && app.contains(sel.anchorNode);
    if (text === lastText || selecting) return;
    lastText = text;
    lastState = JSON.parse(text);
    // Don't rebuild the banner mid-fade (a new element would jump to transparent); the fade's end timer re-renders.
    if (reserveConfirm !== "fading") render(lastState);
  } catch (e) {
    const app = document.getElementById("app");
    if (!lastState) app.replaceChildren(h("p", { class: "err" }, "Could not load state: " + e));
  }
}

refresh();
setInterval(refresh, POLL_MS);
