import { query } from "./_generated/server";
import { v } from "convex/values";
import { dashboard as buildDashboard, type GameRecord } from "./lib/teamStats";
import { leagueStats } from "./lib/leagueStats";
import type { QueryCtx } from "./_generated/server";

/** Every game with at least one hero in its draft, as the statistics read it. */
async function loadGames(ctx: QueryCtx): Promise<GameRecord[]> {
  const rows = await ctx.db.query("games").collect();
  // `data` is the full game record from the extractor. A game pushed before the `checked`
  // column existed was a saved game, so it counts as checked.
  return rows
    .map((row) => ({ ...(row.data as GameRecord), checked: row.checked ?? true }))
    .filter((g) => g.draft.some((a) => a.hero));
}

/** The whole league: standings and the hero pool. `stage` undefined means the match type most
 *  games have, empty means all of them. */
export const league = query({
  args: { stage: v.optional(v.string()) },
  handler: async (ctx, { stage }) => {
    const games = await loadGames(ctx);
    const stages: Record<string, number> = {};
    for (const g of games) stages[g.stage] = (stages[g.stage] ?? 0) + 1;
    const useStage = stage === undefined ? (Object.entries(stages).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "") : stage;
    return leagueStats(games, useStage || null);
  },
});

/** Draft statistics of one team: what the dashboard page shows.
 *  Leave `stage` out for the default, send it empty for all match types. */
export const dashboard = query({
  args: { team: v.optional(v.string()), stage: v.optional(v.string()) },
  handler: async (ctx, { team, stage }) => {
    return buildDashboard(await loadGames(ctx), team, stage);
  },
});
