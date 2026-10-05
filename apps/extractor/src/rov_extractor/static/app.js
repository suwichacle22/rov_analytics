/* RoV draft extractor: form logic. State lives in `game` and mirrors the GameInput model. */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  ref: null,
  series: [],
  current: null,     // series object
  gameNo: null,
  game: null,        // GameInput
  gameKey: null,     // series and game that `game` belongs to
  saved: false,
  review: null,      // what the user still has to check in the open game: { status, count, items }
  recognising: new Set(),  // games with a Recognise request under way
  progress: {},      // how far each of them is: { percent, label }
  pending: {},       // results that came back while another game was open
  timers: {},
  newDateManual: false,  // New match dialog: the user typed the date, keep it
  newDateLookup: null,   // New match dialog: date lookup under way, Create waits for it
  newDateUrl: '',
};

const LANES = ['DSL', 'JGL', 'MID', 'ADL', 'SUP'];
const BAN_SEQ = { 1: 1, 2: 2, 3: 3, 4: 4, 5: 11, 6: 12, 7: 13, 8: 14 };
const PICK_SEQ = { 1: 5, 2: 6, 3: 7, 4: 8, 5: 9, 6: 10, 7: 15, 8: 16, 9: 17, 10: 18 };

// ---------- helpers ----------
function toast(msg, isErr = false, ms = 2800) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.toggle('err', isErr);
  t.hidden = false;
  clearTimeout(state.timers.toast);
  state.timers.toast = setTimeout(() => (t.hidden = true), ms);
}
async function api(method, url, body, isForm = false) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) opts.body = body;
    else { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  }
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok && r.status !== 422) throw new Error(data.detail || r.statusText);
  return data;
}
const debounce = (key, fn, ms) => { clearTimeout(state.timers[key]); state.timers[key] = setTimeout(fn, ms); };
const heroById = id => state.ref.heroes.find(h => h.id === id);
const heroName = id => (heroById(id) || {}).name || id || '';
const stageOf = id => (state.ref.stages || []).find(x => x.id === id) || { id, name: id || '', short: id || '' };
const stageOptions = v => state.ref.stages.map(x => `<option value="${x.id}" ${x.id === v ? 'selected' : ''}>${x.name}</option>`).join('');
const teamName = id => (state.ref.teams.find(t => t.id === id) || {}).name || id;
function heroArt(id, kind) {
  const m = state.ref.artMap && state.ref.artMap[id];
  const file = m && m[kind === 'ban' ? 'ban' : 'pick'];
  return file ? `/api/art/${kind === 'ban' ? 'ban' : 'pick'}/${encodeURIComponent(file)}` : null;
}
function setStatus(text, cls) {
  const el = $('#status-save');
  el.className = 'state ' + (cls || '');
  $('span', el).textContent = text;
}
function parseNum(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).trim().toLowerCase().replace(/,/g, '');
  if (!s) return null;
  const m = s.match(/^(\d+(?:\.\d+)?)\s*(k|m)?$/);
  if (!m) return null;
  let n = parseFloat(m[1]);
  if (m[2] === 'k') n *= 1000; if (m[2] === 'm') n *= 1e6;
  return Math.round(n);
}
function fmtNum(n) { return n === null || n === undefined ? '' : String(n); }
function parseDuration(v) {
  const s = String(v || '').trim();
  const m = s.match(/^(\d{1,2}):(\d{2})$/);
  if (m) return parseInt(m[1]) * 60 + parseInt(m[2]);
  const n = parseInt(s);
  return Number.isFinite(n) ? n : null;
}
function fmtDuration(s) { if (s === null || s === undefined) return ''; return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }

function emptyGame(gameNo) {
  const s = state.current;
  return {
    gameNo, blueTeam: s.teamA, winner: null, durationS: null, patch: null,
    slots: { blueBans: [{}, {}, {}, {}], redBans: [{}, {}, {}, {}], bluePicks: [{}, {}, {}, {}, {}], redPicks: [{}, {}, {}, {}, {}] },
    players: [], teamStats: {}, images: {}, notes: '',
  };
}
function normaliseGame(g) {
  const s = state.current;
  g.slots = g.slots || {};
  for (const k of ['blueBans', 'redBans']) { g.slots[k] = (g.slots[k] || []).slice(0, 4); while (g.slots[k].length < 4) g.slots[k].push({}); }
  for (const k of ['bluePicks', 'redPicks']) { g.slots[k] = (g.slots[k] || []).slice(0, 5); while (g.slots[k].length < 5) g.slots[k].push({}); }
  g.players = g.players || [];
  const red = g.blueTeam === s.teamA ? s.teamB : s.teamA;
  for (const team of [g.blueTeam, red]) {
    const rows = g.players.filter(p => p.team === team);
    while (rows.length < 5) { const r = { team, player: null, hero: null, lane: null, kills: null, deaths: null, assists: null, dmgDealt: null, dmgTaken: null, items: [] }; rows.push(r); g.players.push(r); }
  }
  g.players = g.players.filter(p => p.team === g.blueTeam || p.team === red);
  g.teamStats = g.teamStats || {};
  for (const team of [g.blueTeam, red]) g.teamStats[team] = g.teamStats[team] || { kills: null, gold: null, towers: null, dragons: null, slayers: null };
  g.images = g.images || {};
  return g;
}
const redTeam = () => (state.game.blueTeam === state.current.teamA ? state.current.teamB : state.current.teamA);

// ---------- combobox ----------
function combobox(input, { options, onPick, allowFree = false }) {
  const wrap = document.createElement('div');
  wrap.className = 'combo';
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  const list = document.createElement('ul');
  list.className = 'combo-list';
  list.hidden = true;
  wrap.appendChild(list);
  let items = [], hl = 0;
  const render = () => {
    const q = input.value.trim().toLowerCase();
    items = options().filter(o => !q || o.label.toLowerCase().includes(q) || (o.alt || '').includes(q));
    items.sort((a, b) => {
      if (a.pin !== b.pin) return (b.pin || 0) - (a.pin || 0);
      const as = a.label.toLowerCase().startsWith(q) ? 0 : 1, bs = b.label.toLowerCase().startsWith(q) ? 0 : 1;
      return as - bs || a.label.localeCompare(b.label);
    });
    items = items.slice(0, 40);
    hl = 0;
    list.innerHTML = items.map((o, i) => `<li class="${i === hl ? 'hl' : ''}" data-i="${i}">${o.img ? `<img src="${o.img}" loading="lazy" alt="">` : ''}<span>${o.label}</span>${o.hint ? `<small>${o.hint}</small>` : ''}</li>`).join('');
    list.hidden = items.length === 0;
  };
  const pick = (o) => { input.value = o ? o.label : input.value; list.hidden = true; onPick(o ? o.value : (allowFree ? input.value.trim() : null), o); };
  input.addEventListener('focus', () => { input.select(); render(); });
  input.addEventListener('input', () => { render(); if (allowFree) onPick(input.value.trim(), null); });
  input.addEventListener('keydown', (e) => {
    if (list.hidden && e.key !== 'Enter') return;
    if (e.key === 'ArrowDown') { hl = Math.min(hl + 1, items.length - 1); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { hl = Math.max(hl - 1, 0); e.preventDefault(); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      if (!list.hidden && items[hl]) pick(items[hl]);
      else if (allowFree) pick(null);
      list.hidden = true;
      focusNext(input);
      return;
    } else if (e.key === 'Escape') { list.hidden = true; return; }
    else if (e.key === 'Tab') { if (!list.hidden && items[hl] && input.value.trim() && !allowFree) pick(items[hl]); list.hidden = true; return; }
    else return;
    $$('li', list).forEach((li, i) => li.classList.toggle('hl', i === hl));
    const cur = $('li.hl', list); if (cur) cur.scrollIntoView({ block: 'nearest' });
  });
  input.addEventListener('blur', () => setTimeout(() => {
    list.hidden = true;
    if (!allowFree) {
      const q = input.value.trim().toLowerCase();
      const exact = options().find(o => o.label.toLowerCase() === q);
      if (exact) pick(exact);
      else if (!q) onPick(null, null);
      else { const first = options().find(o => o.label.toLowerCase().includes(q)); if (first) pick(first); else { input.classList.add('invalid'); } }
    }
  }, 120));
  list.addEventListener('mousedown', (e) => { const li = e.target.closest('li'); if (li) { e.preventDefault(); pick(items[+li.dataset.i]); focusNext(input); } });
  return { refresh: render };
}
function focusNext(el) {
  const order = $$('[data-tab]').sort((a, b) => +a.dataset.tab - +b.dataset.tab);
  const i = order.indexOf(el);
  if (i >= 0 && order[i + 1]) order[i + 1].focus();
}

// ---------- boot + routing ----------
async function boot() {
  state.ref = await api('GET', '/api/ref');
  const st = await api('GET', '/api/status');
  const cx = $('#status-convex');
  cx.textContent = st.convexUrl ? 'Convex · connected' : 'Convex · not set';
  cx.title = st.convexUrl || 'Put CONVEX_URL or CONVEX_SELF_HOSTED_URL in .env.local';
  cx.classList.toggle('ok', !!st.convexUrl);
  $('#images-hint').textContent = (st.cloudImages ? 'Stored in Convex' : 'Stay on this PC') + ', named automatically. Ctrl V pastes a copied screenshot.';
  fillSeriesForm();
  await loadSeriesList();
  const openDlg = () => { $('#dlg-series').showModal(); $('#ns-tournament').focus(); };
  $('#btn-new-series').onclick = openDlg;
  $('#btn-new-series-2').onclick = openDlg;
  $('#ns-cancel').onclick = () => $('#dlg-series').close();
  $('#form-series').onsubmit = onCreateSeries;
  document.addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); if (state.game) saveGame(); } });
  window.addEventListener('hashchange', route);
  await route();
}
async function route() {
  const m = location.hash.match(/^#([^/]+)(?:\/(\d+))?$/);
  if (!m) return;
  const [, id, n] = m;
  if (!state.series.some(s => s.seriesId === id)) return;
  if (!state.current || state.current.seriesId !== id) await openSeries(id, +(n || 1), false);
  else if (+(n || 1) !== state.gameNo) await openGame(+(n || 1), false);
}
function setHash(id, n) {
  const h = `#${id}/${n}`;
  if (location.hash !== h) history.replaceState(null, '', h);
}
function fillSeriesForm() {
  $('#ns-stage').innerHTML = stageOptions('leg1');
  const t = $('#ns-tournament');
  t.innerHTML = state.ref.tournaments.map(x => `<option value="${x.id}">${x.name}</option>`).join('');
  const opts = state.ref.teams.map(x => `<option value="${x.id}">${x.id} · ${x.name}</option>`).join('');
  $('#ns-teamA').innerHTML = opts; $('#ns-teamB').innerHTML = opts;
  $('#ns-teamA').value = 'FS'; $('#ns-teamB').value = 'BRU';
  const home = () => { const a = $('#ns-teamA').value, b = $('#ns-teamB').value; $('#ns-home').innerHTML = `<option value="${a}">${a}</option><option value="${b}">${b}</option>`; };
  $('#ns-teamA').onchange = home; $('#ns-teamB').onchange = home; home();
  const form = $('#form-series'), date = $('input[name=date]', form), link = $('input[name=vodUrl]', form);
  const submit = $('button[type=submit]', form);
  date.value = new Date().toISOString().slice(0, 10);
  state.newDateManual = false;
  state.newDateLookup = null;
  state.newDateUrl = '';
  submit.disabled = false; submit.textContent = 'Create match';
  $('#ns-date-hint').textContent = 'today, or from the source link';
  date.oninput = () => { state.newDateManual = true; $('#ns-date-hint').textContent = ''; };
  // The date comes from the video. While it is being read, the Create button waits,
  // so a match is never created with today's date by accident.
  const lookup = async (url) => {
    submit.disabled = true; submit.textContent = 'Reading the date…';
    $('#ns-date-hint').textContent = 'reading the video…';
    try {
      const r = await api('GET', `/api/video-date?url=${encodeURIComponent(url)}`).catch(() => ({}));
      if (asLink(link.value) !== url || state.newDateManual) return;
      if (r.date) date.value = r.date;
      $('#ns-date-hint').textContent = r.date ? 'from the video' : 'not found in the video, check it';
    } finally {
      if (state.newDateUrl === url) {
        state.newDateLookup = null;
        submit.disabled = false; submit.textContent = 'Create match';
      }
    }
  };
  link.onchange = () => {
    const url = asLink(link.value);
    if (!url || state.newDateManual || url === state.newDateUrl) return;
    state.newDateUrl = url;
    state.newDateLookup = lookup(url);
  };
}
async function onCreateSeries(e) {
  e.preventDefault();
  const link = $('input[name=vodUrl]', e.target);
  if (link.onchange) link.onchange(); // Enter inside the link field submits before the lookup started
  if (state.newDateLookup) await state.newDateLookup;
  const fd = new FormData(e.target);
  const body = Object.fromEntries(fd.entries());
  body.bestOf = parseInt(body.bestOf);
  body.vodUrl = asLink(body.vodUrl);
  body.dateManual = state.newDateManual;
  try {
    const s = await api('POST', '/api/series', body);
    $('#dlg-series').close();
    e.target.reset();
    fillSeriesForm();
    await loadSeriesList();
    openSeries(s.seriesId, 1);
  } catch (err) { toast(err.message, true); }
}
// The mark of one game in the match list and on the game tabs: green when saved, red when it holds
// values the user still has to look at, amber for a draft with nothing flagged.
const toCheck = (s, n) => (s.review && s.review[n]) || 0;
const dotClass = (s, n) => (s.games.includes(n) ? 'saved' : !s.drafts.includes(n) ? '' : toCheck(s, n) ? 'check' : 'draft');
const dotTitle = (s, n) => (s.games.includes(n) ? `Game ${n}: saved` : !s.drafts.includes(n) ? `Game ${n}` : toCheck(s, n) ? `Game ${n}: ${toCheck(s, n)} to check` : `Game ${n}: draft, nothing flagged`);

async function loadSeriesList() {
  state.series = await api('GET', '/api/series');
  const ul = $('#series-list');
  ul.innerHTML = state.series.map(s => `
    <li data-id="${s.seriesId}" class="${state.current && state.current.seriesId === s.seriesId ? 'active' : ''}">
      <div class="t"><span>${s.teamA} vs ${s.teamB}</span><span class="bo">Bo${s.bestOf}</span><button type="button" class="more" aria-haspopup="menu" aria-expanded="false" aria-label="Options for ${s.teamA} vs ${s.teamB}" title="Match options">${DOTS}</button></div>
      <div class="m"><span>${s.date}</span><span class="type">${stageOf(s.stage).short}</span><span class="${s.score.winner ? 'won' : ''}">${s.score.wins[s.teamA] || 0}–${s.score.wins[s.teamB] || 0}</span>
        <span class="dots">${Array.from({ length: s.bestOf }, (_, i) => i + 1).map(n => `<i class="dot ${dotClass(s, n)}" data-n="${n}" title="${dotTitle(s, n)}"></i>`).join('')}</span></div>
    </li>`).join('') || '<li class="none small">No matches yet</li>';
  $$('li[data-id]', ul).forEach(li => {
    li.onclick = () => openSeries(li.dataset.id, 1);
    $('.more', li).onclick = (e) => {
      e.stopPropagation();
      toggleMenu(e.currentTarget, [{ label: 'Delete match', danger: true, run: () => deleteSeries(li.dataset.id) }]);
    };
  });
}

// ---------- dropdown menu + confirm ----------
const DOTS = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><circle cx="3" cy="8" r="1.4"/><circle cx="8" cy="8" r="1.4"/><circle cx="13" cy="8" r="1.4"/></svg>';
let menuAnchor = null;
function closeMenu(refocus = false) {
  const m = $('#menu');
  if (m.hidden) return;
  m.hidden = true;
  if (menuAnchor) { menuAnchor.setAttribute('aria-expanded', 'false'); if (refocus) menuAnchor.focus(); }
  menuAnchor = null;
}
function toggleMenu(anchor, items) {
  if (menuAnchor === anchor) { closeMenu(); return; }
  closeMenu();
  const m = $('#menu');
  m.innerHTML = items.map((it, i) => it.sep ? '<hr>' : `<button type="button" role="menuitem" data-i="${i}" class="${it.danger ? 'danger' : ''}">${it.label}</button>`).join('');
  m.hidden = false;
  // The menu is fixed to the viewport so the scrolling rail and the phone's series strip cannot clip it.
  const r = anchor.getBoundingClientRect(), w = m.offsetWidth, h = m.offsetHeight;
  const left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8));
  const top = r.bottom + 4 + h > window.innerHeight - 8 ? Math.max(8, r.top - h - 4) : r.bottom + 4;
  m.style.left = `${left}px`;
  m.style.top = `${top}px`;
  menuAnchor = anchor;
  anchor.setAttribute('aria-expanded', 'true');
  $$('button', m).forEach(b => b.onclick = () => { const it = items[+b.dataset.i]; closeMenu(); it.run(); });
  $('button', m).focus();
}
document.addEventListener('click', (e) => { if (!e.target.closest('#menu, .more')) closeMenu(); });
document.addEventListener('keydown', (e) => {
  const m = $('#menu');
  if (m.hidden) return;
  if (e.key === 'Escape') { e.preventDefault(); closeMenu(true); return; }
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
  e.preventDefault();
  const btns = $$('button', m), i = btns.indexOf(document.activeElement);
  btns[(i + (e.key === 'ArrowDown' ? 1 : btns.length - 1)) % btns.length].focus();
});
window.addEventListener('scroll', () => closeMenu(), true);
window.addEventListener('resize', () => closeMenu());

function confirmDelete({ title, body, action }) {
  const dlg = $('#dlg-confirm');
  $('#confirm-title').textContent = title;
  $('#confirm-body').textContent = body;
  $('#confirm-ok').textContent = action;
  return new Promise((resolve) => {
    const done = (v) => { dlg.onclose = null; if (dlg.open) dlg.close(); resolve(v); };
    $('#confirm-ok').onclick = () => done(true);
    $('#confirm-cancel').onclick = () => done(false);
    dlg.onclose = () => done(false);
    dlg.showModal();
    $('#confirm-cancel').focus();
  });
}
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const where = () => ($('#status-convex').classList.contains('ok') ? 'this PC and Convex' : 'this PC');

async function deleteSeries(id) {
  const s = state.series.find(x => x.seriesId === id);
  if (!s) return;
  const ok = await confirmDelete({
    title: `Delete ${s.teamA} vs ${s.teamB}?`,
    body: `${s.date}, best of ${s.bestOf}, with ${plural(s.games.length, 'saved game')} and ${plural(s.drafts.length, 'draft')}. The match, its games and its screenshots are removed from ${where()}. This cannot be undone.`,
    action: 'Delete match',
  });
  if (!ok) return;
  const isOpen = state.current && state.current.seriesId === id;
  if (isOpen) { clearTimeout(state.timers.autosave); clearTimeout(state.timers.validate); }
  forgetRecognise(gameKey(id, ''));
  try {
    await api('DELETE', `/api/series/${id}`);
    if (isOpen) closeEditor();
    await loadSeriesList();
    toast(`Deleted ${s.teamA} vs ${s.teamB}`);
  } catch (e) { toast(e.message, true); }
}
async function deleteGame(n) {
  const s = state.current;
  const kind = s.games.includes(n) ? 'saved game' : 'draft';
  const ok = await confirmDelete({
    title: `Delete game ${n}?`,
    body: `${s.teamA} vs ${s.teamB}, ${s.date}. The ${kind} and its screenshots are removed from ${where()}. The other games of the match stay. This cannot be undone.`,
    action: `Delete game ${n}`,
  });
  if (!ok) return;
  clearTimeout(state.timers.autosave); clearTimeout(state.timers.validate);
  forgetRecognise(gameKey(s.seriesId, n));
  try {
    await api('DELETE', `/api/series/${s.seriesId}/games/${n}`);
    await loadSeriesList();
    state.current = await api('GET', `/api/series/${s.seriesId}`);
    renderScore();
    await openGame(n);
    toast(`Deleted game ${n}`);
  } catch (e) { toast(e.message, true); }
}
function closeEditor() {
  state.current = null; state.game = null; state.gameNo = null; state.gameKey = null; state.saved = false;
  $('#editor').hidden = true;
  $('#checks').hidden = true;
  $('#crumbs').hidden = true;
  $('#empty-state').hidden = false;
  setStatus('Idle', '');
  history.replaceState(null, '', location.pathname);
}

// ---------- series + game ----------
async function openSeries(id, gameNo, push = true) {
  state.current = await api('GET', `/api/series/${id}`);
  $('#empty-state').hidden = true;
  $('#editor').hidden = false;
  $('#checks').hidden = false;
  $('#crumbs').hidden = false;
  $('#crumb-series').textContent = `${state.current.teamA} vs ${state.current.teamB}`;
  $('#series-title').textContent = `${teamName(state.current.teamA)} vs ${teamName(state.current.teamB)}`;
  const st = state.current;
  $('#series-stage').innerHTML = stageOptions(st.stage);
  $('#series-stage').onchange = (e) => setStage(e.target.value);
  $('#series-source').onchange = (e) => setSource(e.target.value);
  $('#series-date').onchange = (e) => setDate(e.target.value);
  renderMatchHead();
  renderScore();
  $$('#series-list li').forEach(li => li.classList.toggle('active', li.dataset.id === id));
  renderGameTabs();
  await openGame(gameNo, push);
}
function renderMatchHead() {
  const st = state.current;
  $('#series-sub').textContent = [st.tournament, st.date, st.patch && `patch ${st.patch}`, `home ${st.homeTeam}`].filter(Boolean).join(' · ');
  $('#series-date').value = st.date || '';
  $('#series-source').value = st.vodUrl || '';
}
async function setDate(date) {
  const s = state.current;
  try {
    if (!date) throw new Error('A match needs a date');
    const r = await api('PATCH', `/api/series/${s.seriesId}`, { date, dateManual: true });
    s.date = r.date; s.dateManual = r.dateManual;
    await loadSeriesList();
    toast(r.cloudError ? `Date saved here. Convex update failed: ${r.cloudError}` : `Date: ${r.date}`, !!r.cloudError);
  } catch (e) { toast(e.message, true); }
  if (state.current === s) renderMatchHead();
}
// Recognise reads the day of the match from the source link and reports it with the result.
function matchFromRecognise(s, match) {
  if (!match || !match.dateChanged) return;
  s.date = match.date;
  if (state.current === s) renderMatchHead();
  loadSeriesList();
}
const asLink = (text) => { const v = (text || '').trim(); return v && !/^https?:\/\//i.test(v) ? `https://${v}` : v; };
async function setSource(text) {
  const s = state.current;
  try {
    const r = await api('PATCH', `/api/series/${s.seriesId}`, { vodUrl: asLink(text) });
    s.vodUrl = r.vodUrl;
    s.date = r.date;
    if (r.cloudError) toast(`Source link saved here. Convex update failed: ${r.cloudError}`, true);
    else toast(r.vodUrl ? 'Source link saved' : 'Source link removed');
  } catch (e) { toast(e.message, true); }
  if (state.current === s) renderMatchHead();
}
async function setStage(stage) {
  const s = state.current, before = s.stage;
  try {
    const r = await api('PATCH', `/api/series/${s.seriesId}`, { stage });
    s.stage = r.stage;
    await loadSeriesList();
    const renamed = r.renamed || {};
    for (const kind of ['draft', 'post']) if (renamed[state.game.images[kind]]) state.game.images[kind] = renamed[state.game.images[kind]];
    renderImages();
    const n = Object.keys(renamed).length;
    if (r.cloudError) toast(`Match type saved here. Convex update failed: ${r.cloudError}`, true);
    else toast(`Match type: ${stageOf(r.stage).name}` + (n ? ` · ${plural(n, 'screenshot')} renamed` : '') + (r.cloud && r.cloud.pushed ? ` · ${plural(r.cloud.pushed, 'game')} updated in Convex` : ''));
  } catch (e) {
    $('#series-stage').value = before;
    toast(e.message, true);
  }
}
function renderScore() {
  const s = state.current, sc = s.score || { wins: {}, need: 0 };
  const a = sc.wins[s.teamA] || 0, b = sc.wins[s.teamB] || 0;
  $('#series-score').innerHTML = `${s.teamA} ${a} – ${b} ${s.teamB}<small>${sc.winner ? `${sc.winner} won in game ${sc.decidedIn}` : `Bo${s.bestOf} · first to ${sc.need}`}</small>`;
  $('#series-score').classList.toggle('won', !!sc.winner);
}
function renderGameTabs() {
  const s = state.current;
  const decidedIn = (s.score && s.score.decidedIn) || 99;
  $('#game-tabs').innerHTML = Array.from({ length: s.bestOf }, (_, i) => i + 1).map(n =>
    `<button data-n="${n}" class="${n === state.gameNo ? 'active' : ''} ${n > decidedIn ? 'na' : ''} ${dotClass(s, n) === 'check' ? 'check' : ''}" title="${n > decidedIn ? 'Match already decided' : dotTitle(s, n)}"><i class="dot ${dotClass(s, n)}"></i>G${n}${dotClass(s, n) === 'check' ? `<b class="need">${toCheck(s, n)}</b>` : ''}</button>`).join('');
  $$('#game-tabs button').forEach(b => b.onclick = () => openGame(+b.dataset.n));
}
async function openGame(n, push = true) {
  state.gameNo = n;
  if (push !== false) setHash(state.current.seriesId, n); else setHash(state.current.seriesId, n);
  const r = await api('GET', `/api/series/${state.current.seriesId}/games/${n}`);
  state.game = normaliseGame(r.input || emptyGame(n));
  state.game.gameNo = n;
  state.gameKey = gameKey(state.current.seriesId, n);
  state.saved = r.saved;
  state.review = r.review || null;
  const lanes = fillLanes();
  renderGameTabs();
  renderEditor();
  $('#save-info').textContent = r.saved ? `Saved ${String(r.savedAt || '').replace('T', ' ').slice(0, 16)}. Edits become a draft until you save again.` : 'Not saved yet. Everything autosaves as a draft.';
  setStatus(r.saved ? 'Saved' : 'Draft', r.saved ? 'ok' : 'warn');
  validate();
  if (lanes) changed();
  const waiting = state.pending[state.gameKey];
  if (waiting) { delete state.pending[state.gameKey]; showProposal(waiting); }
}

// ---------- editor rendering ----------
function renderEditor() {
  const g = state.game, s = state.current;
  const teams = [s.teamA, s.teamB];
  const opt = (arr, v, none) => (none ? `<option value="">${none}</option>` : '') + arr.map(t => `<option value="${t}" ${t === v ? 'selected' : ''}>${t}</option>`).join('');
  $('#g-blue').innerHTML = opt(teams, g.blueTeam);
  $('#g-winner').innerHTML = opt(teams, g.winner, 'choose');
  $('#g-duration').value = fmtDuration(g.durationS);
  $('#g-patch').value = g.patch || '';
  $('#g-patch').placeholder = s.patch ? `match: ${s.patch}` : 'optional';
  $('#g-blue').onchange = e => { const old = g.blueTeam; g.blueTeam = e.target.value; if (old !== g.blueTeam) { normaliseGame(state.game); renderEditor(); } changed(); };
  $('#g-winner').onchange = e => { g.winner = e.target.value || null; changed(); };
  $('#g-duration').onchange = e => { g.durationS = parseDuration(e.target.value); e.target.value = fmtDuration(g.durationS); changed(); };
  $('#g-patch').onchange = e => { g.patch = e.target.value.trim() || null; changed(); };

  renderImages();
  renderBar();
  renderPlayers();
  renderStages();
  renderReview();
}

// ---------- what the user still has to check ----------
// The server lists the values of an unsaved game that need a look (review.py): heroes read below
// 90%, empty slots, loosely matched names, a missing winner or game time.
function reviewField(key) {
  const [kind, at] = key.split(':');
  if (kind === 'slot') return $(`.slot[data-key="${at}"] input.hero`);
  if (kind === 'field') return $(at === 'winner' ? '#g-winner' : '#g-duration');
  const [side, i] = at.split('.');
  const tr = $(`#pt-${side}`).children[+i];
  return tr ? $(kind === 'player' ? 'input.pl' : 'select.hero', tr) : null;
}
function confirmReview(items) {
  const g = state.game, red = redTeam();
  for (const it of items) {
    const [kind, at] = it.key.split(':');
    if (kind === 'slot') { const [key, i] = at.split('.'); g.slots[key][+i].confirmed = true; }
    if (kind === 'player') { const [side, i] = at.split('.'); const row = g.players.filter(p => p.team === (side === 'blue' ? g.blueTeam : red))[+i]; if (row) row.confirmed = true; }
  }
  // Take them off the list at once; the autosave answers with the list as the server sees it.
  const done = new Set(items.map(it => it.key));
  state.review.items = state.review.items.filter(it => !done.has(it.key));
  state.review.count = state.review.items.length;
  renderReview();
  changed();
}
function renderReview() {
  const r = state.review || { status: 'none', count: 0, items: [] };
  $$('.slot.check, input.check, select.check').forEach(el => el.classList.remove('check'));
  $$('.slot .flag').forEach(el => el.remove());
  for (const it of r.items) {
    const el = reviewField(it.key);
    if (!el) continue;
    const slot = el.closest('.slot');
    if (slot) {
      slot.classList.add('check');
      slot.title = it.message;
      slot.insertAdjacentHTML('beforeend', `<span class="flag">${it.score != null ? Math.round(it.score * 100) + '%' : '?'}</span>`);
    } else { el.classList.add('check'); el.title = it.message; }
  }
  const c = $('#review-count');
  c.textContent = r.status === 'saved' ? 'saved' : r.count ? `${r.count} to check` : 'nothing flagged';
  c.className = 'count ' + (r.count ? 'bad' : 'ok');
  const ul = $('#review');
  ul.innerHTML = r.items.map((it, i) => `<li><button type="button" class="go" data-i="${i}">${it.message}</button>${it.confirm ? `<button type="button" class="yes" data-i="${i}" title="This value is right">OK</button>` : ''}</li>`).join('')
    || `<li class="ok">${r.status === 'saved' ? 'This game is saved' : r.status === 'none' ? 'Nothing recognised yet' : 'Every value was read with 90% or more'}</li>`;
  $$('button.go', ul).forEach(b => b.onclick = () => { const el = reviewField(r.items[+b.dataset.i].key); if (el) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); el.focus({ preventScroll: true }); } });
  $$('button.yes', ul).forEach(b => b.onclick = () => confirmReview([r.items[+b.dataset.i]]));
  const all = r.items.filter(it => it.confirm);
  $('#btn-confirm-all').hidden = all.length < 2;
  $('#btn-confirm-all').onclick = () => confirmReview(all);
  // The same count on the game tab and in the match list.
  const s = state.current;
  if (s && state.game && r.status !== 'none') {
    s.review = { ...(s.review || {}), [state.gameNo]: r.status === 'saved' ? 0 : r.count };
    if (r.status === 'draft' && !s.games.includes(state.gameNo) && !s.drafts.includes(state.gameNo)) s.drafts = [...s.drafts, state.gameNo];
    renderGameTabs();
    const dot = $(`#series-list li[data-id="${s.seriesId}"] .dot[data-n="${state.gameNo}"]`);
    if (dot) { dot.className = `dot ${dotClass(s, state.gameNo)}`; dot.title = dotTitle(s, state.gameNo); }
  }
}
function renderStages() {
  const g = state.game;
  const setupDone = !!(g.blueTeam && g.winner && g.durationS);
  const imagesDone = !!(g.images.draft && g.images.post);
  const draftDone = ['blueBans', 'redBans', 'bluePicks', 'redPicks'].every(k => g.slots[k].every(e => e.hero));
  const postDone = g.players.length === 10 && g.players.every(p => p.player && p.hero && p.lane);
  $('#s-setup').classList.toggle('done', setupDone);
  $('#s-images').classList.toggle('done', imagesDone);
  $('#s-draft').classList.toggle('done', draftDone);
  $('#s-post').classList.toggle('done', postDone);
}

function renderImages() {
  renderRecogniseBtn();
  for (const kind of ['draft', 'post']) {
    const box = $(`#drop-${kind}`);
    const img = $('img', box);
    const file = state.game.images[kind];
    box.classList.toggle('has', !!file);
    img.hidden = !file;
    $('#btn-recognise').disabled = !(state.game.images.draft || state.game.images.post);
    $('#btn-recognise').title = $('#btn-recognise').disabled ? 'Attach an image first' : 'Read names, numbers, result and hero guesses from the images';
    if (file) { img.src = `/api/series/${state.current.seriesId}/files/${encodeURIComponent(file)}?t=${Date.now()}`; $('.drop-label span', box).textContent = file + (state.game.images[`${kind}Storage`] ? ' · in Convex' : ''); }
    else { img.removeAttribute('src'); $('.drop-label span', box).textContent = DROP_HINT[kind]; }
    const input = $('input[type=file]', box);
    box.onclick = () => input.click();
    box.onmouseenter = () => { state.pasteKind = kind; };
    box.onmouseleave = () => { if (state.pasteKind === kind) state.pasteKind = null; };
    const paste = $('.paste', box);
    paste.hidden = !CAN_READ_CLIPBOARD;
    paste.onclick = (e) => { e.stopPropagation(); pasteFromButton(kind); };
    input.onchange = () => input.files[0] && uploadImage(kind, input.files[0]);
    box.ondragover = e => { e.preventDefault(); box.classList.add('over'); };
    box.ondragleave = () => box.classList.remove('over');
    box.ondrop = e => { e.preventDefault(); box.classList.remove('over'); const f = e.dataTransfer.files[0]; if (f) uploadImage(kind, f); };
  }
}
// ---------- paste from the clipboard ----------
const DROP_HINT = { draft: 'before the swap · click, drop or paste', post: 'full 16:9 · click, drop or paste' };
const IMAGE_EXT = { 'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp' };
// The button needs the async clipboard API, which browsers only allow on localhost or https.
// Ctrl V works everywhere, including the phone address on the home network.
const CAN_READ_CLIPBOARD = !!(window.isSecureContext && navigator.clipboard && navigator.clipboard.read);
function uploadBlob(kind, blob) {
  const ext = IMAGE_EXT[blob.type];
  if (!ext) { toast(`The clipboard holds ${blob.type || 'something that is not an image'}. Copy a png, jpg or webp image.`, true); return; }
  return uploadImage(kind, new File([blob], `clipboard${ext}`, { type: blob.type }));
}
function pasteTarget() {
  if (state.pasteKind) return state.pasteKind;
  const im = state.game.images;
  return !im.draft ? 'draft' : !im.post ? 'post' : null;
}
document.addEventListener('paste', (e) => {
  if (!state.game || document.querySelector('dialog[open]')) return;
  const item = Array.from((e.clipboardData && e.clipboardData.items) || []).find(i => i.kind === 'file' && i.type.startsWith('image/'));
  if (!item) return;
  e.preventDefault();
  const kind = pasteTarget();
  if (!kind) { toast('Both screenshots are set. Point at the one to replace, then paste.', true); return; }
  uploadBlob(kind, item.getAsFile());
});
async function pasteFromButton(kind) {
  try {
    for (const item of await navigator.clipboard.read()) {
      const type = item.types.find(t => t.startsWith('image/'));
      if (type) { await uploadBlob(kind, await item.getType(type)); return; }
    }
    toast('No image on the clipboard. Copy a screenshot first.', true);
  } catch (e) { toast(`Could not read the clipboard: ${e.message}`, true); }
}

async function uploadImage(kind, file) {
  const fd = new FormData();
  fd.append('file', file, file.name);
  try {
    const r = await api('POST', `/api/series/${state.current.seriesId}/games/${state.gameNo}/images/${kind}`, fd, true);
    state.game.images[kind] = r.file;
    if (r.cloud) state.game.images[`${kind}Storage`] = r.cloud;
    renderImages();
    renderStages();
    changed();
    toast(r.cloud ? `Saved ${r.file} and stored in Convex` : r.cloudError ? `Saved ${r.file} locally. Convex upload failed: ${r.cloudError}` : `Saved ${r.file}`, !!r.cloudError);
  } catch (e) { toast(e.message, true); }
}

function layout() { return state.ref.layouts[state.current.layout] || state.ref.layouts.rpl2026; }

function heroOptions(entry) {
  const base = state.ref.heroes.map(h => ({ value: h.id, label: h.name, alt: h.id, img: heroArt(h.id, 'pick') }));
  const cands = (entry && entry.candidates) || [];
  if (!cands.length) return base;
  const first = cands.map(c => { const h = heroById(c.hero); return h ? { value: h.id, label: h.name, alt: h.id, img: heroArt(h.id, 'pick'), hint: `${Math.round(c.score * 100)}%`, pin: 1 } : null; }).filter(Boolean);
  const ids = new Set(first.map(o => o.value));
  return first.concat(base.filter(o => !ids.has(o.value)));
}
function setThumb(slot, heroId, kind) {
  const t = $('.thumb', slot);
  const src = heroId ? heroArt(heroId, kind) : null;
  t.innerHTML = src ? `<img src="${src}" alt="">` : '';
  t.classList.toggle('empty', !src);
}

function renderBar() {
  const g = state.game, L = layout();
  const red = redTeam();
  $('#bar-center').innerHTML = `<div><div class="vs"><span class="b">${g.blueTeam}</span><span class="muted">vs</span><span class="r">${red}</span></div><div class="small muted">Game ${g.gameNo} · Bo${state.current.bestOf}</div></div>`;
  for (const side of ['blue', 'red']) {
    const team = side === 'blue' ? g.blueTeam : red;
    // bans
    const bansEl = $(`#${side}-bans`);
    bansEl.innerHTML = '';
    L[side].banSlots.forEach((banNo, i) => {
      const entry = g.slots[`${side}Bans`][i];
      const slot = document.createElement('div');
      slot.className = `slot ban ${side}`;
      slot.dataset.key = `${side}Bans.${i}`;
      slot.dataset.seq = BAN_SEQ[banNo];
      slot.innerHTML = `<span class="badge">B${banNo}</span><div class="thumb empty"></div><div class="fill"><input class="hero" placeholder="ban" data-tab="${BAN_SEQ[banNo] * 10}" aria-label="Ban ${banNo}"><select class="form" hidden></select></div>`;
      bansEl.appendChild(slot);
      setThumb(slot, entry.hero, 'ban');
      const inp = $('input.hero', slot); inp.value = heroName(entry.hero);
      const formSel = $('select.form', slot);
      const showForm = () => {
        const h = heroById(entry.hero);
        formSel.hidden = !(h && h.forms);
        if (h && h.forms) { formSel.innerHTML = `<option value="">form…</option>` + h.forms.map(f => `<option value="${f}" ${entry.form === f ? 'selected' : ''}>${f}</option>`).join(''); }
      };
      showForm();
      formSel.onchange = () => { entry.form = formSel.value || null; changed(); };
      combobox(inp, { options: () => heroOptions(entry), onPick: (v) => { entry.hero = v; entry.manual = true; entry.confirmed = !!v; if (!v) entry.form = null; inp.classList.remove('invalid'); setThumb(slot, v, 'ban'); showForm(); changed(); } });
      if (entry.heroGuess != null && entry.hero) markGuess(inp, !entry.heroGuess);
    });
    // picks
    const picksEl = $(`#${side}-picks`);
    picksEl.innerHTML = '';
    L[side].pickSlots.forEach((pickNo, i) => {
      const entry = g.slots[`${side}Picks`][i];
      const slot = document.createElement('div');
      slot.className = `slot pick ${side}`;
      slot.dataset.key = `${side}Picks.${i}`;
      slot.dataset.seq = PICK_SEQ[pickNo];
      slot.innerHTML = `<div class="thumb empty"></div><span class="badge">P${pickNo}<small>step ${PICK_SEQ[pickNo]}</small></span><input class="hero" placeholder="hero" data-tab="${PICK_SEQ[pickNo] * 10}" aria-label="Pick ${pickNo}"><div class="played"></div>`;
      picksEl.appendChild(slot);
      setThumb(slot, entry.hero, 'pick');
      const inp = $('input.hero', slot); inp.value = heroName(entry.hero);
      combobox(inp, { options: () => heroOptions(entry), onPick: (v) => { entry.hero = v; entry.manual = true; entry.confirmed = !!v; inp.classList.remove('invalid'); setThumb(slot, v, 'pick'); refreshPlayerHeroSelects(); changed(); } });
      if (entry.heroGuess != null && entry.hero) markGuess(inp, !entry.heroGuess);
    });
  }
  renderSeqLine();
  renderPlayedBy();
}
// Who played each pick comes from the post-game table. The name under a pick on the broadcast is
// only the seat that made the pick, so it is never shown as the player.
function renderPlayedBy() {
  const g = state.game, red = redTeam();
  for (const [side, team] of [['blue', g.blueTeam], ['red', red]]) {
    const rows = g.players.filter(p => p.team === team);
    $$(`#${side}-picks .slot`).forEach((slot, i) => {
      const entry = g.slots[`${side}Picks`][i];
      const row = entry.hero ? rows.find(p => p.hero === entry.hero) : null;
      const el = $('.played', slot);
      el.textContent = row && row.player ? row.player : '—';
      el.classList.toggle('none', !(row && row.player));
      el.title = (row && row.player ? `${row.player} played ${heroName(entry.hero)}, from the post-game table.` : 'Set the player of this hero in the post-game table.')
        + (entry.player ? ` The pick was made from the seat of ${entry.player}.` : '');
    });
  }
}
function renderSeqLine() {
  const g = state.game, L = layout();
  const items = [];
  for (const side of ['blue', 'red']) {
    L[side].banSlots.forEach((n, i) => items.push({ seq: BAN_SEQ[n], side, kind: 'ban', label: `B${n}`, hero: g.slots[`${side}Bans`][i].hero }));
    L[side].pickSlots.forEach((n, i) => items.push({ seq: PICK_SEQ[n], side, kind: 'pick', label: `P${n}`, hero: g.slots[`${side}Picks`][i].hero }));
  }
  items.sort((a, b) => a.seq - b.seq);
  const counts = {};
  items.forEach(it => { if (it.hero) counts[it.hero] = (counts[it.hero] || 0) + 1; });
  $('#seqline').innerHTML = items.map(it => `<li class="${it.side} ${it.kind} ${it.hero ? 'filled' : ''}" title="Step ${it.seq}: ${it.side} ${it.label}${it.hero ? ' ' + heroName(it.hero) : ''}"><b>${it.seq}</b> ${it.hero ? heroName(it.hero) : it.label}</li>`).join('');
  const filled = items.filter(it => it.hero).length;
  const next = items.find(it => !it.hero);
  $('#draft-progress').innerHTML = `<b>${filled}</b> / 18` + (next ? `<span class="next">next ${next.side} ${next.label}</span>` : '<span class="next">complete</span>');
  $$('.slot').forEach(sl => {
    const [key, idx] = sl.dataset.key.split('.');
    const h = state.game.slots[key][+idx].hero;
    sl.classList.toggle('dup', !!h && counts[h] > 1);
    sl.classList.toggle('next', !!next && +sl.dataset.seq === next.seq);
  });
}

function teamPicks(team) {
  const side = team === state.game.blueTeam ? 'blue' : 'red';
  return state.game.slots[`${side}Picks`].map(p => p.hero).filter(Boolean);
}
function renderPlayers() {
  const g = state.game, red = redTeam();
  for (const [side, team] of [['blue', g.blueTeam], ['red', red]]) {
    $(`#pt-${side}-title`).textContent = teamName(team);
    const table = $(`#pt-${side}`).closest('table');
    if (!$('colgroup', table)) table.insertAdjacentHTML('afterbegin', '<colgroup><col class="pl"><col class="hero"><col class="lane"><col class="n"><col class="n"><col class="n"><col class="w"><col class="w"></colgroup>');
    const tb = $(`#pt-${side}`);
    tb.innerHTML = '';
    const rows = g.players.filter(p => p.team === team);
    rows.forEach((p, i) => {
      const t = 300 + (side === 'blue' ? 0 : 50) + i * 8;
      const tr = document.createElement('tr');
      tr.innerHTML = `<td><input class="pl" placeholder="player" data-tab="${t}"></td>
        <td><div class="hero-cell"><img alt="" hidden><select class="hero" data-tab="${t + 1}"></select></div></td>
        <td><select class="lane" data-tab="${t + 2}">${['', ...LANES].map(l => `<option value="${l}" ${p.lane === l ? 'selected' : ''}>${l || '—'}</option>`).join('')}</select></td>
        <td class="r"><input class="k" inputmode="numeric" data-tab="${t + 3}"></td>
        <td class="r"><input class="d" inputmode="numeric" data-tab="${t + 4}"></td>
        <td class="r"><input class="a" inputmode="numeric" data-tab="${t + 5}"></td>
        <td class="r"><input class="dd" placeholder="61.5k" data-tab="${t + 6}"></td>
        <td class="r"><input class="dt" placeholder="141k" data-tab="${t + 7}"></td>`;
      tb.appendChild(tr);
      const pl = $('input.pl', tr); pl.value = p.player || '';
      combobox(pl, { allowFree: true, options: () => rosterOptions(team), onPick: v => {
        p.player = v || null;
        p.confirmed = !!v;
        if (!p.lane || p.laneAuto) { p.lane = laneOf(team, p.player); p.laneAuto = !!p.lane; $('select.lane', tr).value = p.lane || ''; }
        changed();
      } });
      if (p.playerGuess != null && p.player) markGuess(pl, !p.playerGuess);
      const hs = $('select.hero', tr); hs.dataset.team = team; hs._row = p;
      fillHeroSelect(hs, team, p.hero);
      if (p.barSlot != null) { hs.title = `Portrait matched draft-bar slot ${p.barSlot + 1}`; if (p.hero) markGuess(hs, !p.slotGuess); }
      hs.onchange = () => { p.hero = hs.value || null; p.barSlot = null; p.manual = true; fillHeroSelect(hs, team, p.hero); changed(); };
      $('select.lane', tr).onchange = e => { p.lane = e.target.value || null; p.laneAuto = false; changed(); };
      const bind = (cls, key) => { const el = $(`input.${cls}`, tr); el.value = fmtNum(p[key]); el.onchange = () => { p[key] = parseNum(el.value); el.value = fmtNum(p[key]); changed(); }; };
      bind('k', 'kills'); bind('d', 'deaths'); bind('a', 'assists'); bind('dd', 'dmgDealt'); bind('dt', 'dmgTaken');
    });
    // totals
    const ts = g.teamStats[team];
    const tot = $(`#tt-${side}`);
    tot.innerHTML = ['kills', 'gold', 'towers', 'dragons', 'slayers'].map(k => `<label>${k}<input data-k="${k}" placeholder="${k === 'gold' ? '43.5k' : ''}" value="${fmtNum(ts[k])}"></label>`).join('');
    $$('input', tot).forEach(el => el.onchange = () => { ts[el.dataset.k] = parseNum(el.value); el.value = fmtNum(ts[el.dataset.k]); changed(); });
  }
  $('#btn-prefill').onclick = prefillPlayers;
}
// The position a player has in the team master, or null.
function laneOf(team, name) {
  const p = name && (state.ref.roster[team] || []).find(x => x.name.toLowerCase() === name.trim().toLowerCase());
  return (p && p.lane) || null;
}
// Rows without a lane take it from the team master. A lane chosen by hand is never replaced.
function fillLanes() {
  let n = 0;
  for (const p of state.game.players) {
    const lane = !p.lane && laneOf(p.team, p.player);
    if (lane) { p.lane = lane; p.laneAuto = true; n++; }
  }
  return n;
}
function rosterOptions(team) {
  const side = team === state.game.blueTeam ? 'blue' : 'red';
  const fromBar = state.game.slots[`${side}Picks`].map(p => p.player).filter(Boolean);
  const names = Array.from(new Set([...fromBar, ...(state.ref.players[team] || [])]));
  return names.map(n => ({ value: n, label: n }));
}
function fillHeroSelect(sel, team, current) {
  const picks = teamPicks(team);
  const opts = Array.from(new Set([...(current ? [current] : []), ...picks]));
  sel.innerHTML = `<option value="">hero</option>` + opts.map(h => `<option value="${h}" ${h === current ? 'selected' : ''}>${heroName(h)}</option>`).join('');
  const img = sel.previousElementSibling;
  if (img && img.tagName === 'IMG') { const src = current ? heroArt(current, 'pick') : null; img.hidden = !src; if (src) img.src = src; }
}
function refreshPlayerHeroSelects() {
  $$('table.players select.hero').forEach(sel => fillHeroSelect(sel, sel.dataset.team, sel._row.hero));
}
function prefillPlayers() {
  const g = state.game, red = redTeam();
  for (const [side, team] of [['blue', g.blueTeam], ['red', red]]) {
    const picks = g.slots[`${side}Picks`];
    const rows = g.players.filter(p => p.team === team);
    picks.forEach((pk, i) => { if (rows[i] && pk.player && !rows[i].player) rows[i].player = pk.player; });
  }
  fillLanes();
  renderPlayers();
  changed();
  toast('Names copied from the draft bar. Choose the hero each player played.');
}

// ---------- recognition ----------
function markGuess(el, confident) {
  if (!el) return;
  el.classList.remove('guess', 'sure');
  el.classList.add(confident ? 'sure' : 'guess');
  const clear = () => el.classList.remove('guess', 'sure');
  el.addEventListener('input', clear, { once: true });
  el.addEventListener('change', clear, { once: true });
}
const gameKey = (seriesId, n) => `${seriesId}/${n}`;
const isOpenGame = (key) => !!state.current && state.gameKey === key && gameKey(state.current.seriesId, state.gameNo) === key;
function forgetRecognise(prefix) {
  for (const key of [...state.recognising]) if (key.startsWith(prefix)) state.recognising.delete(key);
  for (const key of Object.keys(state.pending)) if (key.startsWith(prefix)) delete state.pending[key];
}
function renderRecogniseBtn() {
  const btn = $('#btn-recognise');
  const busy = !!state.current && state.recognising.has(gameKey(state.current.seriesId, state.gameNo));
  btn.classList.toggle('busy', busy);
  btn.textContent = busy ? 'Recognising…' : 'Recognise';
  const box = $('#recognise-progress');
  box.hidden = !busy;
  if (!busy) { $('.bar i', box).style.width = '0'; return; }
  const p = state.progress[gameKey(state.current.seriesId, state.gameNo)] || { percent: 0, label: 'Starting' };
  $('.bar', box).setAttribute('aria-valuenow', p.percent);
  $('.bar i', box).style.width = `${p.percent}%`;
  $('.what', box).textContent = p.label;
  $('.pct', box).textContent = `${p.percent}%`;
}
async function watchProgress(seriesId, n) {
  const key = gameKey(seriesId, n);
  while (state.recognising.has(key)) {
    try {
      const r = await api('GET', `/api/series/${seriesId}/games/${n}/recognise/progress`);
      // The bar never moves back, also not when the request has not reached the server yet.
      if (r.running && state.recognising.has(key)) state.progress[key] = { percent: Math.max(r.percent, (state.progress[key] || {}).percent || 0), label: r.label };
    } catch (e) { /* the next round asks again */ }
    renderRecogniseBtn();
    await new Promise(done => setTimeout(done, 500));
  }
  delete state.progress[key];
}
async function recogniseGame() {
  // The answer takes a while and another game may be open by then, so it goes to the game that asked.
  const s = state.current, n = state.gameNo, key = gameKey(s.seriesId, n);
  const name = () => (state.current && state.current.seriesId === s.seriesId ? `Game ${n}` : `${s.teamA} vs ${s.teamB} game ${n}`);
  state.recognising.add(key);
  renderRecogniseBtn();
  watchProgress(s.seriesId, n);
  setStatus('Recognising', 'warn');
  try {
    const r = await api('POST', `/api/series/${s.seriesId}/games/${n}/recognise`, state.game);
    if (!state.recognising.has(key)) return;  // deleted meanwhile
    matchFromRecognise(s, r.match);
    if (isOpenGame(key)) showProposal(r);
    else { state.pending[key] = r; toast(`${name()} is recognised. Open it to fill in the values.`, false, 9000); }
  } catch (e) { toast(isOpenGame(key) ? e.message : `${name()}: ${e.message}`, true); }
  finally { state.recognising.delete(key); renderRecogniseBtn(); }
}
function showProposal(r) {
  state.proposal = r;
  if (r.errors && r.errors.length) toast(r.errors.join(' · '), true);
  applyProposal(r);
}
function applyProposal(r) {
  const g = state.game;
  const red = redTeam();
  let filled = 0;
  const changes = [];
  if (r.draft) {
    const L = layout();
    const label = (key, i) => (key.endsWith('Bans') ? 'B' + L[key.slice(0, -4)].banSlots[i] : 'P' + L[key.slice(0, -5)].pickSlots[i]);
    const sure = new Set();
    for (const key of ['blueBans', 'redBans', 'bluePicks', 'redPicks']) {
      r.draft.slots[key].forEach((s, i) => {
        const entry = g.slots[key][i];
        entry.candidates = s.candidates || [];
        if (s.empty) return;
        if (s.hero && s.confident) sure.add(s.hero);
        if (!entry.hero && s.hero) { entry.hero = s.hero; entry.heroGuess = !s.confident; entry.confirmed = false; filled++; }
        else if (entry.hero && s.hero && s.confident && entry.hero !== s.hero && !entry.manual) {
          // The screenshots are certain and say something else than the field.
          changes.push(`${label(key, i)} ${heroName(entry.hero)} to ${heroName(s.hero)}`);
          entry.hero = s.hero; entry.heroGuess = false; entry.confirmed = false;
        } else if (entry.hero && entry.hero === s.hero) entry.heroGuess = !s.confident;
        if (key.endsWith('Picks') && s.player) entry.player = s.player;
      });
    }
    // A field that repeats a hero the screenshots place elsewhere for certain was a wrong guess.
    for (const key of ['blueBans', 'redBans', 'bluePicks', 'redPicks']) {
      r.draft.slots[key].forEach((s, i) => {
        const entry = g.slots[key][i];
        if (entry.hero && !entry.manual && sure.has(entry.hero) && !(s.confident && s.hero === entry.hero)) {
          changes.push(`${label(key, i)} ${heroName(entry.hero)} cleared`);
          entry.hero = null; entry.heroGuess = null; entry.confirmed = false;
        }
      });
    }
    if (r.draft.fields.gameNo && r.draft.fields.gameNo !== g.gameNo) toast(`Caption says game ${r.draft.fields.gameNo}, you are on game ${g.gameNo}`, true);
  }
  if (r.post) {
    const f = r.post.fields;
    if (!g.winner && f.winner) g.winner = f.winner;
    if (!g.durationS && f.durationS) g.durationS = f.durationS;
    for (const [side, team] of [['blue', g.blueTeam], ['red', red]]) {
      const rows = g.players.filter(p => p.team === team);
      const picks = g.slots[`${side}Picks`];
      (r.post.players[side] || []).forEach((pr, i) => {
        const row = rows[i]; if (!row) return;
        if (!row.player && pr.player) { row.player = pr.player; row.playerGuess = !pr.playerConfident; row.confirmed = false; filled++; }
        for (const k of ['kills', 'deaths', 'assists', 'dmgDealt', 'dmgTaken']) if (row[k] == null && pr[k] != null) { row[k] = pr[k]; filled++; }
        if (pr.barSlot != null && !row.manual) {
          row.barSlot = pr.barSlot; row.slotGuess = !pr.slotConfident;
          const hero = picks[pr.barSlot] && picks[pr.barSlot].hero;
          if (pr.slotConfident && hero && row.hero && row.hero !== hero) { changes.push(`${row.player || 'row ' + (i + 1)} ${heroName(row.hero)} to ${heroName(hero)}`); row.hero = hero; }
        } else if (!row.hero && pr.hero) { row.hero = pr.hero; row.slotGuess = !pr.heroConfident; filled++; }
      });
      // A row that still names a hero the team did not pick was filled from an earlier wrong guess.
      const mine = new Set(picks.map(p => p.hero).filter(Boolean));
      rows.forEach(row => {
        if (!row.hero || row.manual || mine.has(row.hero)) return;
        row.hero = (row.barSlot != null && picks[row.barSlot] && picks[row.barSlot].hero) || null;
        row.slotGuess = true;
      });
      const ts = g.teamStats[team];
      for (const k of ['kills', 'gold', 'towers', 'dragons', 'slayers']) if (ts[k] == null && r.post.teamStats[side][k] != null) { ts[k] = r.post.teamStats[side][k]; filled++; }
    }
  }
  resolveSlotHeroes();
  filled += fillLanes();
  renderEditor();
  changed();
  const open = ['blueBans', 'redBans', 'bluePicks', 'redPicks'].reduce((n, key) => n + g.slots[key].filter(e => !e.hero).length, 0);
  const parts = [`Filled ${plural(filled, 'field')}`];
  if (r.match && r.match.dateChanged) parts.push(`match date set to ${r.match.date} from the video`);
  else if (r.match && r.match.dateNote) parts.push(r.match.dateNote);
  if (changes.length) parts.push(`corrected ${changes.join(', ')}`);
  if (open) parts.push(`${plural(open, 'hero')} left for you to choose`);
  toast(parts.join(' · '), false, changes.length || open || parts.length > 1 ? 9000 : 2800);
}
function resolveSlotHeroes() {
  const g = state.game, red = redTeam();
  for (const [side, team] of [['blue', g.blueTeam], ['red', red]]) {
    const picks = g.slots[`${side}Picks`];
    g.players.filter(p => p.team === team).forEach(row => {
      if (row.barSlot != null && picks[row.barSlot] && picks[row.barSlot].hero && !row.hero) row.hero = picks[row.barSlot].hero;
    });
  }
}

// ---------- change, validate, save ----------
function changed() {
  state.saved = false;
  resolveSlotHeroes();
  renderSeqLine();
  renderPlayedBy();
  renderStages();
  setStatus('Editing', 'warn');
  debounce('autosave', autosave, 700);
  debounce('validate', validate, 350);
}
async function autosave() {
  const key = state.gameKey;
  try {
    const r = await api('PUT', `/api/series/${state.current.seriesId}/games/${state.gameNo}/draft`, state.game);
    setStatus('Draft saved', 'warn');
    // The answer may arrive after another game was opened; the list belongs to the game that asked.
    if (r.review && isOpenGame(key)) { state.review = r.review; renderReview(); }
  } catch (e) { setStatus('Autosave failed', 'bad'); }
}
async function validate() {
  const r = await api('POST', `/api/series/${state.current.seriesId}/games/${state.gameNo}/validate`, state.game);
  const ul = $('#issues');
  const errors = r.issues.filter(i => i.level === 'error'), warns = r.issues.filter(i => i.level === 'warning');
  const c = $('#issue-count');
  c.textContent = errors.length ? `${errors.length} to fix` : warns.length ? `${warns.length} warning${warns.length > 1 ? 's' : ''}` : 'ready';
  c.className = 'count ' + (errors.length ? 'bad' : 'ok');
  ul.innerHTML = (errors.length ? '' : '<li class="ok">Draft rules pass</li>') + r.issues.map(i => `<li class="${i.level}">${i.message}</li>`).join('');
  $('#btn-save').disabled = !r.valid;
  $('#btn-push').disabled = !state.saved;
  return r.valid;
}
async function saveGame() {
  const r = await api('PUT', `/api/series/${state.current.seriesId}/games/${state.gameNo}`, state.game);
  if (!r.ok) { toast('Not saved: fix the errors first', true); await validate(); return; }
  state.saved = true;
  setStatus('Saved', 'ok');
  $('#save-info').textContent = `Saved to ${r.path.split(/[\\/]/).slice(-2).join('/')}` + (r.learnedCrops ? ` · ${r.learnedCrops} hero crops learned` : '');
  $('#btn-push').disabled = false;
  toast(`Saved ${r.gameId}`);
  const ref = await api('GET', '/api/ref');
  state.ref.players = ref.players;
  state.ref.roster = ref.roster;
  await loadSeriesList();
  state.current = await api('GET', `/api/series/${state.current.seriesId}`);
  state.review = { status: 'saved', count: 0, items: [] };
  renderReview();
  renderScore();
}
async function pushGame() {
  const r = await api('POST', `/api/series/${state.current.seriesId}/games/${state.gameNo}/push`);
  if (r.ok) toast('Pushed to Convex'); else toast(`Push failed: ${r.error}`, true);
}
$('#btn-game-menu').onclick = (e) => toggleMenu(e.currentTarget, [
  { label: `Delete game ${state.gameNo}`, danger: true, run: () => deleteGame(state.gameNo) },
  { sep: true },
  { label: 'Delete match', danger: true, run: () => deleteSeries(state.current.seriesId) },
]);
$('#btn-save').onclick = saveGame;
$('#btn-push').onclick = pushGame;
$('#btn-recognise').onclick = recogniseGame;

boot().catch(e => toast(e.message, true));
