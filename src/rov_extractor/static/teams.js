/* Teams page: the players of each team and the position they play. */
const state = { teams: [], lanes: [], dirty: false };
const $ = (s, el = document) => el.querySelector(s);
const LANE_NAMES = { DSL: "Dark Slayer lane", JGL: "Jungle", MID: "Mid lane", ADL: "Abyssal Dragon lane", SUP: "Support" };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: opts.body ? { "Content-Type": "application/json" } : {}, ...opts });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  t.hidden = false;
  clearTimeout(toast.h);
  toast.h = setTimeout(() => (t.hidden = true), err ? 5000 : 2600);
}

function setDirty(v) {
  state.dirty = v;
  $("#status-save span").textContent = v ? "Unsaved changes" : "Saved";
  $("#status-save").className = "state " + (v ? "warn" : "ok");
}

async function load() {
  Object.assign(state, await api("/api/teams"));
  render();
  setDirty(false);
}

function coverage(team, el) {
  const named = team.players.filter(p => p.name.trim());
  const missing = state.lanes.filter(l => !named.some(p => p.lane === l));
  const unset = named.filter(p => !p.lane).length;
  const parts = [];
  if (missing.length) parts.push(`No player for ${missing.join(", ")}`);
  if (unset) parts.push(`${unset} without a position`);
  el.textContent = parts.join(" · ") || "All five positions covered";
  el.className = "cover" + (parts.length ? " warn" : "");
}

function playerRow(team, p, card) {
  const row = document.createElement("div");
  row.className = "row";
  row.innerHTML = `<input class="pl" placeholder="player name" aria-label="Player name">
    <select aria-label="Position"><option value="">no position</option>${state.lanes.map(l => `<option value="${l}">${l} · ${LANE_NAMES[l] || l}</option>`).join("")}</select>
    <button type="button" class="btn ghost remove" title="Remove player" aria-label="Remove player">×</button>`;
  const name = $("input", row), lane = $("select", row);
  name.value = p.name;
  lane.value = p.lane || "";
  const touched = () => { setDirty(true); $(".count", card).textContent = count(team); coverage(team, $(".cover", card)); };
  name.oninput = () => { p.name = name.value; touched(); };
  lane.onchange = () => { p.lane = lane.value || null; touched(); };
  $(".remove", row).onclick = () => {
    team.players.splice(team.players.indexOf(p), 1);
    row.remove();
    if (!team.players.length) $(".roster", card).append(none());
    touched();
  };
  return row;
}

const count = (team) => { const n = team.players.filter(p => p.name.trim()).length; return `${n} player${n === 1 ? "" : "s"}`; };
const none = () => Object.assign(document.createElement("div"), { className: "none", textContent: "No players yet" });

function teamCard(team) {
  const card = document.createElement("section");
  card.className = "card";
  card.innerHTML = `<div class="team-head"><h3></h3><span class="name"></span><span class="count"></span></div>
    <div class="roster"><div class="cols"><span>Player</span><span>Position</span><span></span></div></div>
    <div class="team-foot"><span class="cover"></span><button type="button" class="btn small">Add player</button></div>`;
  $("h3", card).textContent = team.id;
  $(".name", card).textContent = team.name;
  $(".count", card).textContent = count(team);
  const roster = $(".roster", card);
  if (team.players.length) team.players.forEach(p => roster.append(playerRow(team, p, card)));
  else roster.append(none());
  coverage(team, $(".cover", card));
  $(".team-foot button", card).onclick = () => {
    const p = { name: "", lane: null };
    team.players.push(p);
    const empty = $(".none", roster);
    if (empty) empty.remove();
    const row = playerRow(team, p, card);
    roster.append(row);
    $("input", row).focus();
    setDirty(true);
  };
  return card;
}

function render() {
  const q = $("#filter").value.trim().toLowerCase();
  const shown = state.teams.filter(t => !q || t.id.toLowerCase().includes(q) || t.name.toLowerCase().includes(q) || t.players.some(p => p.name.toLowerCase().includes(q)));
  const box = $("#teams");
  box.replaceChildren(...shown.map(teamCard));
  if (!shown.length) box.innerHTML = `<div class="hint">No team or player matches the filter.</div>`;
}

async function save() {
  try {
    const players = Object.fromEntries(state.teams.map(t => [t.id, t.players]));
    Object.assign(state, await api("/api/teams", { method: "PUT", body: JSON.stringify({ players }) }));
    render();
    setDirty(false);
    toast("Teams saved");
  } catch (e) { toast(e.message, true); }
}

$("#filter").oninput = render;
$("#btn-save").onclick = save;
document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); } });
window.addEventListener("beforeunload", (e) => { if (state.dirty) e.preventDefault(); });
load().catch(e => toast(e.message, true));
