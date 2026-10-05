// The league as a whole: standings and the heroes of the whole draft pool. Pure functions, like
// teamStats.ts. Every game counts once here, so a hero picked by either side is one pick.

import type { GameRecord } from "./teamStats";

const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

const avg = (values: number[]): number | null =>
  values.length ? Math.round(values.reduce((a, b) => a + b, 0) / values.length) : null;

export interface Standing {
  team: string;
  matches: { wins: number; losses: number; open: number };
  games: { wins: number; losses: number };
  sides: { blue: { wins: number; losses: number }; red: { wins: number; losses: number } };
  avgDurationS: number | null;
  /** Heroes this team picks in a larger share of its games than the league does: its signature. */
  signature: { hero: string; games: number; share: number; leagueShare: number }[];
  /** Every game in date order, for a form line. */
  form: { seriesId: string; opp: string; n: number; date: string; won: boolean | null }[];
}

export interface LeagueHero {
  hero: string;
  picks: number;
  bans: number;
  /** Share of games where the hero was picked or banned. */
  presence: number;
  /** Record of the side that picked it. */
  wins: number;
  losses: number;
  /** Teams that picked it, with how many games each. */
  teams: Record<string, number>;
  /** Bans by phase. */
  ban1: number;
  ban2: number;
  /** How often it was the very first pick of the game. */
  first: number;
}

export function leagueStats(allGames: GameRecord[], stage: string | null) {
  const games = allGames
    .filter((g) => !stage || g.stage === stage)
    .sort((a, b) => cmp(a.date, b.date) || cmp(a.seriesId, b.seriesId) || a.gameNo - b.gameNo);

  const teams = new Map<string, Standing & { durations: number[]; picks: Map<string, number>; series: Map<string, { bestOf: number; wins: number; losses: number }> }>();
  const team = (id: string) => {
    let t = teams.get(id);
    if (!t) {
      t = { team: id, matches: { wins: 0, losses: 0, open: 0 }, games: { wins: 0, losses: 0 },
        sides: { blue: { wins: 0, losses: 0 }, red: { wins: 0, losses: 0 } }, avgDurationS: null, signature: [], form: [],
        durations: [], picks: new Map(), series: new Map() };
      teams.set(id, t);
    }
    return t;
  };
  const heroes = new Map<string, LeagueHero>();
  const hero = (id: string) => {
    let h = heroes.get(id);
    if (!h) {
      h = { hero: id, picks: 0, bans: 0, presence: 0, wins: 0, losses: 0, teams: {}, ban1: 0, ban2: 0, first: 0 };
      heroes.set(id, h);
    }
    return h;
  };
  const sides = { blue: { wins: 0, losses: 0 }, red: { wins: 0, losses: 0 } };
  const durations: number[] = [];
  const coverage = { games: games.length, checked: 0, noWinner: 0, unnamed: 0, slots: 0, matches: new Set<string>() };

  for (const g of games) {
    coverage.matches.add(g.seriesId);
    if (g.checked) coverage.checked += 1;
    if (!g.winner) coverage.noWinner += 1;
    if (g.durationS) durations.push(g.durationS);
    for (const side of ["blue", "red"] as const) {
      const id = g[side], t = team(id), opp = side === "blue" ? g.red : g.blue;
      const won = g.winner ? g.winner === id : null;
      if (won !== null) {
        const key = won ? "wins" : "losses";
        t.games[key] += 1;
        t.sides[side][key] += 1;
        if (side === "blue") sides.blue[key] += 1;
        else sides.red[key] += 1;
      }
      if (g.durationS) t.durations.push(g.durationS);
      t.form.push({ seriesId: g.seriesId, opp, n: g.gameNo, date: g.date, won });
      let s = t.series.get(g.seriesId);
      if (!s) {
        s = { bestOf: g.bestOf, wins: 0, losses: 0 };
        t.series.set(g.seriesId, s);
      }
      if (won !== null) s[won ? "wins" : "losses"] += 1;
    }
    const seen = new Set<string>();
    for (const a of g.draft) {
      coverage.slots += 1;
      if (!a.hero) { coverage.unnamed += 1; continue; }
      const h = hero(a.hero);
      if (a.action === "ban") {
        h.bans += 1;
        h[a.phase === "ban1" ? "ban1" : "ban2"] += 1;
      } else {
        h.picks += 1;
        h.teams[a.team] = (h.teams[a.team] ?? 0) + 1;
        if (a.order === 1) h.first += 1;
        if (g.winner) h[g.winner === a.team ? "wins" : "losses"] += 1;
        const t = team(a.team);
        t.picks.set(a.hero, (t.picks.get(a.hero) ?? 0) + 1);
      }
      seen.add(a.hero);
    }
    for (const id of seen) hero(id).presence += 1;
  }

  const n = games.length || 1;
  const heroList = [...heroes.values()]
    .map((h) => ({ ...h, presence: Math.round((h.presence / n) * 1000) / 1000 }))
    .sort((a, b) => b.presence - a.presence || b.picks - a.picks || cmp(a.hero, b.hero));
  const leagueShare = new Map(heroList.map((h) => [h.hero, h.picks / (2 * n)]));

  const standings: Standing[] = [...teams.values()].map((t) => {
    for (const s of t.series.values()) {
      const need = Math.floor(s.bestOf / 2) + 1;
      t.matches[s.wins >= need ? "wins" : s.losses >= need ? "losses" : "open"] += 1;
    }
    const played = t.form.length || 1;
    const signature = [...t.picks.entries()]
      .map(([id, games]) => ({ hero: id, games, share: games / played, leagueShare: leagueShare.get(id) ?? 0 }))
      .filter((x) => x.games >= 3 && x.share >= 2 * x.leagueShare)
      .sort((a, b) => b.share - b.leagueShare - (a.share - a.leagueShare) || b.games - a.games)
      .slice(0, 3)
      .map((x) => ({ ...x, share: Math.round(x.share * 1000) / 1000, leagueShare: Math.round(x.leagueShare * 1000) / 1000 }));
    const { durations: d, picks: _p, series: _s, ...rest } = t;
    return { ...rest, avgDurationS: avg(d), signature };
  }).sort((a, b) =>
    b.matches.wins - a.matches.wins || a.matches.losses - b.matches.losses ||
    (b.games.wins - b.games.losses) - (a.games.wins - a.games.losses) || b.games.wins - a.games.wins || cmp(a.team, b.team));

  const stages: Record<string, number> = {};
  for (const g of allGames) stages[g.stage] = (stages[g.stage] ?? 0) + 1;

  return {
    stage: stage ?? "",
    coverage: { games: coverage.games, checked: coverage.checked, noWinner: coverage.noWinner, unnamed: coverage.unnamed, slots: coverage.slots, matches: coverage.matches.size },
    sides,
    avgDurationS: avg(durations),
    standings,
    heroes: heroList,
    options: { stages },
  };
}

export type League = ReturnType<typeof leagueStats>;
