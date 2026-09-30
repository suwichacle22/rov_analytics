/* Dashboard: draft statistics of one team, read from /api/stats. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const state = { ref: null, heroes: {}, art: {}, crops: { ban: {}, pick: {} }, stats: null, tips: [] };

const LANE_NAMES = { DSL: 'Dark Slayer lane', JGL: 'Jungle', MID: 'Mid lane', ADL: 'Abyssal Dragon lane', SUP: 'Support' };
const ORDINAL = ['1st', '2nd', '3rd', '4th', '5th'];

async function api(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

// ---------- small helpers
const heroName = id => (state.heroes[id] || {}).name || id;
const teamName = id => (state.ref.teams.find(t => t.id === id) || {}).name || id;
const stageName = id => (state.ref.stages.find(s => s.id === id) || {}).name || id;
function heroImg(id) {
  const m = state.art[id] || {};
  if (m.pick) return `/api/art/pick/${encodeURIComponent(m.pick)}`;
  for (const kind of ['pick', 'ban']) {
    const files = state.crops[kind][id];
    if (files && files.length) return `/api/crops/${kind}/${encodeURIComponent(id)}/${encodeURIComponent(files[0])}`;
  }
  return null;
}
function hero(id) {
  const src = heroImg(id);
  return `<span class="hero">${src ? `<img src="${src}" alt="" loading="lazy">` : '<i class="noart"></i>'}<span>${esc(heroName(id))}</span></span>`;
}
const clock = s => (s == null ? '–' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`);
const rate = (w, l) => (w + l ? `${Math.round((100 * w) / (w + l))}%` : '–');
const record = (w, l) => `${w}–${l}`;
const plural = (n, word, many) => `${n} ${n === 1 ? word : many || word + 's'}`;
const num = v => (v == null ? '–' : Number(v).toLocaleString('en-US'));

// A count as a thin bar with the number at its tip.
function bar(n, max) {
  return `<span class="meter"><i style="width:${max ? Math.max(3, (100 * n) / max) : 0}%"></i></span><span class="n num">${n}</span>`;
}
// Wins against losses: the split shows the share, the text carries the numbers.
function winLoss(w, l) {
  if (!(w + l)) return '<span class="muted">–</span>';
  const parts = [];
  if (w) parts.push(`<i class="w" style="flex:${w}"></i>`);
  if (l) parts.push(`<i class="l" style="flex:${l}"></i>`);
  return `<span class="wl">${parts.join('')}</span><span class="num">${record(w, l)}</span><span class="pct num muted">${rate(w, l)}</span>`;
}
function counts(obj, label = k => k) {
  return Object.entries(obj || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${esc(label(k))}${v > 1 ? ` <span class="muted num">×${v}</span>` : ''}`).join(', ');
}
function tipFor(title, where, extra) {
  state.tips.push({ title, where, extra });
  return `tabindex="0" data-tip="${state.tips.length - 1}"`;
}
function card(title, hint, body, cls = '') {
  return `<section class="panel ${cls}"><header><h2>${esc(title)}</h2>${hint ? `<p class="hint">${hint}</p>` : ''}</header>${body}</section>`;
}
const none = text => `<p class="none muted">${esc(text)}</p>`;

// ---------- sections
function tiles(s) {
  const r = s.record, g = r.games, b = r.sides.blue, d = r.sides.red, m = r.matches;
  const tile = (label, value, sub) => `<div class="tile"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`;
  return `<div class="tiles">
    ${tile('Matches', record(m.wins, m.losses), m.open ? `${plural(m.open, 'match', 'matches')} not decided in the data` : `${rate(m.wins, m.losses)} won`)}
    ${tile('Games', record(g.wins, g.losses), `${rate(g.wins, g.losses)} won`)}
    ${tile('<i class="side blue"></i>Blue side', record(b.wins, b.losses), `${rate(b.wins, b.losses)} won in ${plural(b.games, 'game')}`)}
    ${tile('<i class="side red"></i>Red side', record(d.wins, d.losses), `${rate(d.wins, d.losses)} won in ${plural(d.games, 'game')}`)}
    ${tile('Average game time', clock(r.avgDurationS), `wins ${clock(r.avgWinS)} · losses ${clock(r.avgLossS)}`)}
  </div>`;
}

function matches(s) {
  const rows = s.matches.map(m => {
    const chips = m.games.map(g => {
      const result = g.won == null ? '?' : g.won ? 'W' : 'L';
      const words = [`Game ${g.n}`, `${g.side} side`, g.won == null ? 'no winner entered' : g.won ? 'won' : 'lost', clock(g.durationS)];
      if (g.unnamed) words.push(`${plural(g.unnamed, 'slot')} without a hero`);
      if (!g.checked) words.push('not checked yet');
      return `<a class="chip ${g.won ? 'won' : g.won === false ? 'lost' : ''}" href="/#${encodeURIComponent(m.seriesId)}/${g.n}" title="${esc(words.join(' · '))}"><i class="side ${g.side}"></i>G${g.n} <b>${result}</b>${g.unnamed ? '<i class="todo"></i>' : ''}</a>`;
    }).join('');
    const res = m.won == null ? 'open' : m.won ? 'Won' : 'Lost';
    return `<tr><td class="num muted">${esc(m.date)}</td><td>${esc(teamName(m.opp))}</td><td><span class="res ${m.won ? 'won' : ''}">${res}</span> <span class="num">${record(m.wins, m.losses)}</span></td><td class="chips">${chips}</td></tr>`;
  }).join('');
  const legend = '<p class="legend"><span><i class="side blue"></i>blue side</span><span><i class="side red"></i>red side</span><span><b>W</b> won</span><span><b>L</b> lost</span><span><i class="todo"></i>a slot has no hero yet</span><span>A game opens in the form.</span></p>';
  return card('Matches', '', `<table class="grid"><thead><tr><th>Date</th><th>Opponent</th><th>Result</th><th>Games</th></tr></thead><tbody>${rows}</tbody></table>${legend}`, 'wide');
}

function whereLine(w, kind) {
  const bits = [`vs ${esc(w.opp)} G${w.n}`, w.won == null ? '' : w.won ? 'won' : 'lost'];
  if (kind === 'pick' || kind === 'opp') bits.push(w.player ? esc(w.player) : '', w.order ? `pick ${w.order}` : '');
  if (kind === 'ban') bits.push(w.phase === 'ban1' ? 'first ban phase' : 'second ban phase');
  return bits.filter(Boolean).join(' · ');
}

function heroTable(rows, cols, kind, limit = 12) {
  if (!rows.length) return none('Nothing in these games yet.');
  const max = Math.max(...rows.map(r => r.games));
  const body = rows.map((r, i) => `<tr class="${i >= limit ? 'extra' : ''}" ${tipFor(heroName(r.hero), r.where.map(w => whereLine(w, kind)))}>
    <td>${hero(r.hero)}</td><td class="qty">${bar(r.games, max)}</td>${cols.map(c => `<td class="${c.cls || ''}">${c.cell(r)}</td>`).join('')}</tr>`).join('');
  const more = rows.length > limit ? `<button type="button" class="btn small ghost showall">Show all ${rows.length}</button>` : '';
  return `<table class="grid heroes"><thead><tr><th>Hero</th><th>Games</th>${cols.map(c => `<th>${c.head}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table>${more}`;
}
const colWL = { head: 'Won–lost', cls: 'wlcell', cell: r => winLoss(r.wins, r.losses) };
const colPhase = { head: 'Ban phase', cls: 'muted', cell: r => counts(r.phases, k => (k === 'ban1' ? 'first' : 'second')) };

function pools(s) {
  if (!s.players.length) return '';
  const cols = s.players.map(p => {
    const rows = p.heroes.map(h => `<tr ${tipFor(`${p.player} on ${heroName(h.hero)}`, h.where.map(w => whereLine(w)))}><td class="name">${hero(h.hero)}</td><td class="num played">${h.games}</td><td class="wlcell">${winLoss(h.wins, h.losses)}</td></tr>`).join('');
    return `<div class="pool"><div class="pool-head"><b>${esc(p.player)}</b><span class="muted">${esc(LANE_NAMES[p.lane] || p.lane || 'no position set')}</span><span class="muted num">${plural(p.heroes.length, 'hero', 'heroes')} in ${plural(p.games, 'game')}</span></div>
      <table class="grid heroes"><thead><tr><th>Hero</th><th>Games</th><th>Won–lost</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }).join('');
  return card('Hero pool of each player', 'Who played what, taken from the post-game screen. A swap after the draft is already counted for the player who played the hero.', `<div class="pools">${cols}</div>`, 'wide');
}

function laneOrder(s) {
  const lanes = Object.keys(s.laneOrder);
  const max = Math.max(1, ...lanes.flatMap(l => s.laneOrder[l]));
  const total = lanes.reduce((n, l) => n + s.laneOrder[l].reduce((a, b) => a + b, 0), 0);
  if (!total) return card('Position by pick order', '', none('No pick has a position yet. Set the positions on the Teams page.'));
  const rows = lanes.map(l => `<tr><th scope="row">${esc(LANE_NAMES[l] || l)}</th>${s.laneOrder[l].map((v, i) => {
    const a = v / max;
    return `<td class="heat ${a > 0.55 ? 'dark' : ''}" style="background:rgba(255,255,255,${(0.03 + 0.82 * a).toFixed(3)})" title="${esc(LANE_NAMES[l] || l)} was the ${ORDINAL[i]} pick of the team in ${plural(v, 'game')}">${v || ''}</td>`;
  }).join('')}</tr>`).join('');
  return card('Position by pick order', 'In how many games each position was the team\'s 1st to 5th pick. Brighter means more often.',
    `<table class="heatmap"><thead><tr><th></th>${ORDINAL.map(o => `<th>${o}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>`);
}

function answers(s) {
  if (!s.answers.length) return card('Answers to an opponent pick', '', none('No pair has come up twice yet.'));
  const rows = s.answers.slice(0, 12).map(a => `<tr><td>${hero(a.after)}</td><td class="arrow muted">then</td><td>${hero(a.then)}</td><td class="num">${a.games}</td><td class="wlcell">${winLoss(a.wins, a.games - a.wins)}</td></tr>`).join('');
  return card('Answers to an opponent pick', 'The opponent picked the left hero, and the team picked the right one in its next turn. Pairs seen at least twice.',
    `<table class="grid heroes"><thead><tr><th>Opponent picked</th><th></th><th>Team picked</th><th>Games</th><th>Won–lost</th></tr></thead><tbody>${rows}</tbody></table>`);
}

function meta(s) {
  const n = s.coverage.games;
  const rows = s.meta.slice(0, 15);
  const max = Math.max(1, ...rows.map(r => r.picks + r.bans));
  const body = rows.map(r => `<tr title="${esc(`${heroName(r.hero)}: picked ${r.teamPicks} by the team and ${r.oppPicks} by opponents, banned ${r.teamBans} by the team and ${r.oppBans} by opponents`)}">
    <td>${hero(r.hero)}</td>
    <td class="qty"><span class="meter split">${[['pick', r.picks], ['ban', r.bans]].filter(x => x[1]).map(([k, v]) => `<i class="${k}" style="width:${(100 * v) / max}%"></i>`).join('')}</span><span class="n num">${Math.round(100 * r.presence)}%</span></td>
    <td class="num">${r.picks}</td><td class="num">${r.bans}</td><td class="wlcell">${winLoss(r.wins, r.losses)}</td></tr>`).join('');
  return card('Most contested heroes', `Picked or banned by either team, as a share of the ${plural(n, 'game')}. Won–lost is the record of the team that picked the hero.`,
    `<table class="grid heroes"><thead><tr><th>Hero</th><th>In the draft</th><th>Picks</th><th>Bans</th><th>Won–lost</th></tr></thead><tbody>${body}</tbody></table>
     <p class="legend"><span><i class="key pick"></i>picked</span><span><i class="key ban"></i>banned</span></p>`);
}

function playersTable(s) {
  if (!s.players.length) return '';
  const rows = s.players.map(p => {
    const g = p.kdaGames || 0;
    const avg = v => (g ? (v / g).toFixed(1) : '–');
    const kda = g ? ((p.kills + p.assists) / Math.max(1, p.deaths)).toFixed(1) : '–';
    return `<tr><td><b>${esc(p.player)}</b></td><td class="muted">${esc(p.lane || '–')}</td><td class="num">${p.heroes.length}</td><td class="num">${avg(p.kills)} / ${avg(p.deaths)} / ${avg(p.assists)}</td><td class="num">${kda}</td><td class="num">${num(p.avgDmgDealt)}</td><td class="num">${num(p.avgDmgTaken)}</td><td class="num muted">${g} of ${p.games}</td></tr>`;
  }).join('');
  return card('Players', 'Averages per game from the post-game screen. The last column says in how many games the three numbers could be read.',
    `<table class="grid"><thead><tr><th>Player</th><th>Position</th><th>Heroes</th><th>K / D / A</th><th>KDA</th><th>Damage dealt</th><th>Damage taken</th><th>Games read</th></tr></thead><tbody>${rows}</tbody></table>`);
}

function totals(s) {
  const names = { kills: 'Kills', towers: 'Towers', dragons: 'Dragons', slayers: 'Dark Slayers', gold: 'Gold' };
  const rows = Object.keys(names).map(k => {
    const a = s.totals.team[k], b = s.totals.opp[k];
    const f = v => (v.avg == null ? '–' : k === 'gold' ? num(Math.round(v.avg)) : v.avg.toFixed(1));
    return `<tr><td>${names[k]}</td><td class="num">${f(a)}</td><td class="num">${f(b)}</td><td class="num muted">${Math.min(a.games, b.games)}</td></tr>`;
  }).join('');
  return card('Per game', 'Averages from the post-game totals.',
    `<table class="grid"><thead><tr><th></th><th>${esc(s.team)}</th><th>Opponents</th><th>Games read</th></tr></thead><tbody>${rows}</tbody></table>`);
}

function notice(s) {
  const c = s.coverage, el = $('#notice');
  const parts = [];
  const open = c.games - c.checked;
  if (open) parts.push(`<b>${open} of ${plural(c.games, 'game')}</b> ${open === 1 ? 'comes' : 'come'} straight from Recognise and ${open === 1 ? 'is' : 'are'} not checked and saved yet, so single numbers can be wrong.`);
  if (c.unnamed) parts.push(`${plural(c.unnamed, 'draft slot')} of ${c.slots} ${c.unnamed === 1 ? 'has' : 'have'} no hero and ${c.unnamed === 1 ? 'is' : 'are'} left out of the hero tables.`);
  if (c.noWinner) parts.push(`${plural(c.noWinner, 'game')} ${c.noWinner === 1 ? 'has' : 'have'} no winner.`);
  el.hidden = !parts.length;
  el.innerHTML = parts.join(' ');
}

function render() {
  const s = state.stats;
  state.tips = [];
  $('#title').textContent = `${teamName(s.team)}${s.stage ? ` · ${stageName(s.stage)}` : ''}`;
  document.title = `${s.team} dashboard · RoV Draft Extractor`;
  notice(s);
  if (!s.coverage.games) { $('#body').innerHTML = none('No game of this team in this match type yet.'); return; }
  const o = s.openers, blueGames = s.record.sides.blue.games, redGames = s.record.sides.red.games;
  const pickCols = [colWL, { head: 'Played by', cls: 'muted', cell: r => counts(r.players) || '–' }];
  $('#body').innerHTML = `
    ${tiles(s)}
    ${matches(s)}
    <div class="cols two">
      ${card('Picks', 'Heroes the team picked, most often first.', heroTable(s.picks, pickCols, 'pick'))}
      ${card('Picked against the team', 'Heroes the opponents picked. Won–lost is the team\'s record in those games.', heroTable(s.oppPicks, [colWL], 'opp'))}
    </div>
    ${pools(s)}
    <div class="cols two">
      ${card('Bans by the team', '', heroTable(s.bans, [colPhase], 'ban', 10))}
      ${card('Bans against the team', 'What opponents take away from this team.', heroTable(s.bansAgainst, [colPhase], 'ban', 10))}
    </div>
    <div class="cols three">
      ${card('First pick on blue side', `The opening pick in the ${plural(blueGames, 'game')} on blue side.`, heroTable(o.blue, [colWL], 'pick', 8))}
      ${card('First two picks on red side', `Picks 2 and 3 in the ${plural(redGames, 'game')} on red side.`, heroTable(o.red, [colWL], 'pick', 8))}
      ${card('Opponent\'s first pick', `What opponents opened with in the ${plural(redGames, 'game')} the team was on red side.`, heroTable(o.faced, [colWL], 'opp', 8))}
    </div>
    <div class="cols two">
      ${laneOrder(s)}
      ${answers(s)}
    </div>
    <div class="cols two">
      ${meta(s)}
      <div class="stack">${totals(s)}${playersTable(s)}</div>
    </div>`;
  $$('.showall').forEach(b => b.onclick = () => { b.previousElementSibling.classList.add('all'); b.remove(); });
}

// ---------- tooltip: the games behind a row, on hover and on keyboard focus
function showTip(el, x, y) {
  const t = state.tips[+el.dataset.tip], tip = $('#tip');
  if (!t) return;
  tip.innerHTML = `<b>${esc(t.title)}</b>${t.where.map(w => `<div>${w}</div>`).join('')}`;
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  tip.style.left = `${Math.max(8, Math.min(x + 14, window.innerWidth - r.width - 8))}px`;
  tip.style.top = `${Math.max(8, Math.min(y + 14, window.innerHeight - r.height - 8))}px`;
}
function wireTips() {
  const body = $('#body'), tip = $('#tip');
  body.addEventListener('mousemove', e => { const el = e.target.closest('[data-tip]'); if (el) showTip(el, e.clientX, e.clientY); else tip.hidden = true; });
  body.addEventListener('mouseleave', () => { tip.hidden = true; });
  body.addEventListener('focusin', e => { const el = e.target.closest('[data-tip]'); if (el) { const r = el.getBoundingClientRect(); showTip(el, r.left + 40, r.bottom - 8); } });
  body.addEventListener('focusout', () => { tip.hidden = true; });
}

// ---------- load
async function load() {
  const q = new URLSearchParams(location.search);
  const params = new URLSearchParams();
  if (q.get('team')) params.set('team', q.get('team'));
  if (q.has('stage')) params.set('stage', q.get('stage'));
  const body = $('#body');
  body.classList.add('stale');
  try {
    state.stats = await api(`/api/stats?${params}`);
  } catch (e) { body.innerHTML = none(e.message); body.classList.remove('stale'); return; }
  const o = state.stats.options, s = state.stats;
  const teams = Object.keys(o.teams).sort((a, b) => o.teams[b] - o.teams[a] || a.localeCompare(b));
  $('#f-team').innerHTML = teams.map(t => `<option value="${esc(t)}" ${t === s.team ? 'selected' : ''}>${esc(t)} · ${esc(teamName(t))} (${plural(o.teams[t], 'game')})</option>`).join('');
  $('#f-stage').innerHTML = `<option value="">All match types</option>` + state.ref.stages.filter(x => o.stages[x.id]).map(x => `<option value="${x.id}" ${x.id === s.stage ? 'selected' : ''}>${esc(x.name)} (${plural(o.stages[x.id], 'game')})</option>`).join('');
  render();
  body.classList.remove('stale');
}
function go() {
  const q = new URLSearchParams();
  q.set('team', $('#f-team').value);
  q.set('stage', $('#f-stage').value);
  history.replaceState(null, '', `?${q}`);
  load();
}

(async () => {
  try {
    const [ref, heroes] = await Promise.all([api('/api/ref'), api('/api/heroes')]);
    state.ref = ref;
    state.heroes = Object.fromEntries(heroes.heroes.map(h => [h.id, h]));
    state.art = heroes.map || {};
    state.crops = heroes.crops || state.crops;
  } catch (e) { $('#body').innerHTML = none(e.message); return; }
  $('#f-team').onchange = go;
  $('#f-stage').onchange = go;
  wireTips();
  load();
})();
