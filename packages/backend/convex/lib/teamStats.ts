// Draft statistics of one team, computed from game records. Pure functions: no database access,
// so the same code can be tested with plain objects.
//
// A slot without a hero is left out of the hero tables and counted in `coverage`.

import { LANES } from "./ref";

/** One step of the draft, as the extractor writes it into a game record. */
export interface DraftAction {
  seq: number;
  phase: "ban1" | "pick1" | "ban2" | "pick2";
  order: number; // ban number 1..8 or pick number 1..10
  side: "blue" | "red";
  team: string;
  action: "ban" | "pick";
  hero: string | null;
  player?: string | null; // who played the hero, from the post-game screen
  lane?: string | null;
}

export interface PlayerRow {
  team: string;
  player?: string | null;
  hero?: string | null;
  lane?: string | null;
  kills?: number | null;
  deaths?: number | null;
  assists?: number | null;
  dmgDealt?: number | null;
  dmgTaken?: number | null;
}

/** A game record: what `rov-extract push` sends, stored in `games.data`. */
export interface GameRecord {
  gameId: string;
  seriesId: string;
  stage: string;
  bestOf: number;
  gameNo: number;
  date: string;
  blue: string;
  red: string;
  winner?: string | null;
  durationS?: number | null;
  draft: DraftAction[];
  players?: PlayerRow[];
  teamStats?: Record<string, Partial<Record<TeamStatKey, number | null>>>;
  checked: boolean;
}

const TEAM_STATS = ["kills", "gold", "towers", "dragons", "slayers"] as const;
export type TeamStatKey = (typeof TEAM_STATS)[number];

// Pick numbers that are made in one turn, in draft order.
const TURNS = [[1], [2, 3], [4, 5], [6], [7], [8, 9], [10]];

/** One game behind a count, shown in the tooltip of a row. */
export interface Where {
  opp: string;
  n: number;
  date: string;
  won: boolean | null;
  player?: string | null;
  order?: number;
  phase?: string;
}

export interface HeroRow {
  hero: string;
  games: number;
  // In how many different matches. A team cannot pick a hero twice in one match, so for picks this
  // is the honest share: "picked in 7 of 8 matches".
  matches: number;
  wins: number;
  losses: number;
  where: Where[];
  players?: Record<string, number>;
  phases?: Record<string, number>;
}

class Tally {
  private rows = new Map<string, HeroRow>();
  private seen = new Map<string, Set<string>>();

  add(hero: string, game: { seriesId: string; opp: string; gameNo: number; date: string; won: boolean | null }, extra: Partial<Where> = {}): HeroRow {
    let row = this.rows.get(hero);
    if (!row) {
      row = { hero, games: 0, matches: 0, wins: 0, losses: 0, where: [] };
      this.rows.set(hero, row);
      this.seen.set(hero, new Set());
    }
    const seen = this.seen.get(hero)!;
    seen.add(game.seriesId);
    row.matches = seen.size;
    row.games += 1;
    if (game.won === true) row.wins += 1;
    else if (game.won === false) row.losses += 1;
    row.where.push({ opp: game.opp, n: game.gameNo, date: game.date, won: game.won, ...extra });
    return row;
  }

  list(): HeroRow[] {
    return [...this.rows.values()].sort((a, b) => b.games - a.games || b.wins - a.wins || cmp(a.hero, b.hero));
  }
}

// Plain code point order, the same order the extractor's Python sort uses.
const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

const bump = (row: HeroRow, key: "players" | "phases", value: string | null | undefined) => {
  if (value == null) return;
  const counts = (row[key] ??= {});
  counts[value] = (counts[value] ?? 0) + 1;
};

const avg = (values: number[], digits = 0): number | null => {
  if (!values.length) return null;
  const v = values.reduce((a, b) => a + b, 0) / values.length;
  const f = 10 ** digits;
  return Math.round(v * f) / f;
};

export function teamStats(allGames: GameRecord[], team: string, stage: string | null) {
  const games = allGames
    .filter((g) => (g.blue === team || g.red === team) && (!stage || g.stage === stage))
    .sort((a, b) => cmp(a.date, b.date) || cmp(a.seriesId, b.seriesId) || a.gameNo - b.gameNo);

  const picks = new Tally(), bans = new Tally(), bansVs = new Tally(), oppPicks = new Tally();
  const firstBlue = new Tally(), firstRed = new Tally(), firstFaced = new Tally();
  const meta = new Map<string, { hero: string; picks: number; bans: number; wins: number; losses: number; teamPicks: number; teamBans: number; oppPicks: number; oppBans: number; presence: number }>();
  const players = new Map<string, { lanes: Record<string, number>; games: number; heroes: Tally; kda: [number, number, number]; kdaGames: number; dmgDealt: number[]; dmgTaken: number[] }>();
  const laneOrder: Record<string, number[]> = Object.fromEntries(LANES.map((l) => [l, [0, 0, 0, 0, 0]]));
  const pairs = new Map<string, { after: string; then: string; games: number; wins: number }>();
  const matches = new Map<string, { seriesId: string; date: string; opp: string; bestOf: number; stage: string; wins: number; losses: number; won: boolean | null;
    games: { n: number; side: "blue" | "red"; won: boolean | null; durationS: number | null; checked: boolean; unnamed: number }[] }>();
  const sides = { blue: { games: 0, wins: 0, losses: 0 }, red: { games: 0, wins: 0, losses: 0 } };
  const durations: Record<"all" | "wins" | "losses", number[]> = { all: [], wins: [], losses: [] };
  const totals = { team: {} as Record<TeamStatKey, number[]>, opp: {} as Record<TeamStatKey, number[]> };
  for (const k of TEAM_STATS) { totals.team[k] = []; totals.opp[k] = []; }
  const coverage = { games: games.length, checked: 0, slots: 0, unnamed: 0, noWinner: 0 };

  for (const g of games) {
    const side = g.blue === team ? "blue" : "red";
    const opp = side === "blue" ? g.red : g.blue;
    const won = g.winner ? g.winner === team : null;
    const result = won === null ? null : won ? "wins" : "losses";
    const ref = { seriesId: g.seriesId, opp, gameNo: g.gameNo, date: g.date, won };
    if (g.checked) coverage.checked += 1;
    if (result === null) coverage.noWinner += 1;
    sides[side].games += 1;
    if (result) sides[side][result] += 1;
    if (g.durationS) {
      durations.all.push(g.durationS);
      if (result) durations[result].push(g.durationS);
    }
    for (const [who, name] of [["team", team], ["opp", opp]] as const) {
      for (const k of TEAM_STATS) {
        const v = g.teamStats?.[name]?.[k];
        if (v != null) totals[who][k].push(v);
      }
    }

    let m = matches.get(g.seriesId);
    if (!m) {
      m = { seriesId: g.seriesId, date: g.date, opp, bestOf: g.bestOf, stage: g.stage, wins: 0, losses: 0, won: null, games: [] };
      matches.set(g.seriesId, m);
    }
    m.games.push({ n: g.gameNo, side, won, durationS: g.durationS ?? null, checked: g.checked, unnamed: g.draft.filter((a) => !a.hero).length });
    if (result) m[result] += 1;

    let mineNo = 0;
    const byOrder = new Map<number, DraftAction>();
    for (const a of g.draft) {
      coverage.slots += 1;
      if (a.action === "pick") byOrder.set(a.order, a);
      const hero = a.hero;
      if (!hero) { coverage.unnamed += 1; continue; }
      const mine = a.team === team;
      let row = meta.get(hero);
      if (!row) {
        row = { hero, picks: 0, bans: 0, wins: 0, losses: 0, teamPicks: 0, teamBans: 0, oppPicks: 0, oppBans: 0, presence: 0 };
        meta.set(hero, row);
      }
      if (a.action === "ban") {
        row.bans += 1;
        row[mine ? "teamBans" : "oppBans"] += 1;
        bump((mine ? bans : bansVs).add(hero, ref, { phase: a.phase }), "phases", a.phase);
        continue;
      }
      row.picks += 1;
      row[mine ? "teamPicks" : "oppPicks"] += 1;
      if (won !== null) row[won === mine ? "wins" : "losses"] += 1; // the record of the team that picked the hero
      if (!mine) {
        oppPicks.add(hero, ref, { player: a.player ?? null });
        if (a.order === 1) firstFaced.add(hero, ref);
        continue;
      }
      mineNo += 1;
      bump(picks.add(hero, ref, { player: a.player ?? null, order: a.order }), "players", a.player);
      if (a.lane && a.lane in laneOrder) laneOrder[a.lane][mineNo - 1] += 1;
      if (a.order === 1) firstBlue.add(hero, ref, { player: a.player ?? null });
      else if (a.order === 2 || a.order === 3) firstRed.add(hero, ref, { player: a.player ?? null });
    }

    // What the team picked right after the opponent's picks: every own turn is paired with the
    // opponent's turns that came just before it.
    const turns = TURNS.map((turn) => turn.flatMap((o) => byOrder.get(o) ?? []));
    turns.forEach((acts, i) => {
      if (!acts.length || acts[0].team !== team) return;
      let j = i - 1;
      while (j >= 0 && turns[j].length && turns[j][0].team === team) j -= 1;
      const before: DraftAction[] = [];
      while (j >= 0 && turns[j].length && turns[j][0].team !== team) { before.push(...turns[j]); j -= 1; }
      for (const x of before) for (const y of acts) {
        if (!x.hero || !y.hero) continue;
        const key = `${x.hero}>${y.hero}`;
        const p = pairs.get(key) ?? { after: x.hero, then: y.hero, games: 0, wins: 0 };
        p.games += 1;
        if (won) p.wins += 1;
        pairs.set(key, p);
      }
    });

    for (const p of g.players ?? []) {
      if (p.team !== team || !p.player) continue;
      let row = players.get(p.player);
      if (!row) {
        row = { lanes: {}, games: 0, heroes: new Tally(), kda: [0, 0, 0], kdaGames: 0, dmgDealt: [], dmgTaken: [] };
        players.set(p.player, row);
      }
      row.games += 1;
      if (p.lane) row.lanes[p.lane] = (row.lanes[p.lane] ?? 0) + 1;
      if (p.hero) row.heroes.add(p.hero, ref);
      if (p.kills != null && p.deaths != null && p.assists != null) {
        row.kdaGames += 1;
        row.kda[0] += p.kills; row.kda[1] += p.deaths; row.kda[2] += p.assists;
      }
      if (p.dmgDealt != null) row.dmgDealt.push(p.dmgDealt);
      if (p.dmgTaken != null) row.dmgTaken.push(p.dmgTaken);
    }
  }

  const record = { wins: 0, losses: 0, open: 0 };
  for (const m of matches.values()) {
    const need = Math.floor(m.bestOf / 2) + 1;
    m.won = m.wins >= need ? true : m.losses >= need ? false : null;
    record[m.won === null ? "open" : m.won ? "wins" : "losses"] += 1;
  }

  const laneIndex = (lane: string | null) => { const i = LANES.indexOf(lane as (typeof LANES)[number]); return i < 0 ? LANES.length : i; };
  const playerList = [...players.entries()].map(([player, row]) => {
    const lane = Object.entries(row.lanes).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
    return { player, lane, games: row.games, heroes: row.heroes.list(), kills: row.kda[0], deaths: row.kda[1], assists: row.kda[2],
      kdaGames: row.kdaGames, avgDmgDealt: avg(row.dmgDealt), avgDmgTaken: avg(row.dmgTaken) };
  }).sort((a, b) => laneIndex(a.lane) - laneIndex(b.lane) || b.games - a.games);

  const metaList = [...meta.values()].sort((a, b) => b.picks + b.bans - (a.picks + a.bans) || b.picks - a.picks || cmp(a.hero, b.hero));
  for (const r of metaList) r.presence = Math.round(((r.picks + r.bans) / (games.length || 1)) * 1000) / 1000;

  const totalsOut = Object.fromEntries((["team", "opp"] as const).map((who) =>
    [who, Object.fromEntries(TEAM_STATS.map((k) => [k, { avg: avg(totals[who][k], 1), games: totals[who][k].length }]))])) as
    Record<"team" | "opp", Record<TeamStatKey, { avg: number | null; games: number }>>;

  return {
    team,
    stage: stage ?? "",
    coverage: { ...coverage, matches: matches.size },
    record: {
      matches: record,
      games: { wins: sides.blue.wins + sides.red.wins, losses: sides.blue.losses + sides.red.losses },
      sides,
      avgDurationS: avg(durations.all), avgWinS: avg(durations.wins), avgLossS: avg(durations.losses),
    },
    matches: [...matches.values()].sort((a, b) => cmp(a.date, b.date) || cmp(a.seriesId, b.seriesId)),
    picks: picks.list(),
    bans: bans.list(),
    bansAgainst: bansVs.list(),
    oppPicks: oppPicks.list(),
    players: playerList,
    openers: { blue: firstBlue.list(), red: firstRed.list(), faced: firstFaced.list() },
    laneOrder,
    // Pairs seen at least twice, most frequent first. Equal counts keep the order they first appeared in.
    answers: [...pairs.values()].filter((p) => p.games >= 2).sort((a, b) => b.games - a.games),
    meta: metaList,
    totals: totalsOut,
  };
}

/** What the dashboard shows. Without a team it takes the one with the most games. `stage`
 *  undefined means no choice was made: the team's only match type, or all of them. An empty
 *  string asks for all match types. */
export function dashboard(games: GameRecord[], team: string | undefined, stage: string | undefined) {
  const teams: Record<string, number> = {};
  for (const g of games) {
    teams[g.blue] = (teams[g.blue] ?? 0) + 1;
    teams[g.red] = (teams[g.red] ?? 0) + 1;
  }
  const chosen = team && team in teams ? team : Object.entries(teams).sort((a, b) => b[1] - a[1])[0]?.[0] ?? team ?? "";
  const stages: Record<string, number> = {};
  for (const g of games) if (g.blue === chosen || g.red === chosen) stages[g.stage] = (stages[g.stage] ?? 0) + 1;
  const stageIds = Object.keys(stages);
  const useStage = stage === undefined ? (stageIds.length === 1 ? stageIds[0] : "") : stage;
  return { ...teamStats(games, chosen, useStage || null), options: { teams, stages } };
}

export type TeamStats = ReturnType<typeof teamStats>;
export type Dashboard = ReturnType<typeof dashboard>;
