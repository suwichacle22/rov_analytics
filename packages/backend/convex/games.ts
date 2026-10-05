import { mutation, query } from "./_generated/server";
import { v } from "convex/values";
import type { DraftAction } from "./lib/teamStats";

/** Upsert a series and one game, replacing that game's draft actions. Called by `rov-extract push`.
 *  The same game id is used for the unchecked draft and the saved game, so saving replaces the draft. */
export const upsert = mutation({
  args: { series: v.any(), game: v.any() },
  handler: async (ctx, { series, game }) => {
    const existingSeries = await ctx.db
      .query("series")
      .withIndex("by_seriesId", (q) => q.eq("seriesId", series.seriesId))
      .unique();
    const seriesRow = {
      seriesId: series.seriesId,
      tournament: series.tournament,
      stage: series.stage,
      bestOf: series.bestOf,
      date: series.date,
      teamA: series.teamA,
      teamB: series.teamB,
      homeTeam: series.homeTeam,
      winner: series.winner ?? null,
      vodUrl: series.vodUrl || null,
      data: series,
    };
    if (existingSeries) await ctx.db.replace(existingSeries._id, seriesRow);
    else await ctx.db.insert("series", seriesRow);

    // A saved game calls the sides `blue` and `red`; `blueTeam` is the name in the form input.
    const blueTeam = game.blue ?? game.input?.blueTeam ?? game.blueTeam;
    const redTeam = game.red ?? (blueTeam === series.teamA ? series.teamB : series.teamA);
    const gameRow = {
      gameId: game.gameId,
      seriesId: series.seriesId,
      gameNo: game.gameNo,
      blueTeam,
      redTeam,
      winner: game.winner ?? null,
      durationS: game.durationS ?? null,
      patch: game.patch ?? null,
      savedAt: game.savedAt,
      // A draft pushed with `rov-extract push --drafts` says checked: false. A saved game says nothing.
      checked: game.checked ?? true,
      data: game,
    };
    const existingGame = await ctx.db
      .query("games")
      .withIndex("by_gameId", (q) => q.eq("gameId", game.gameId))
      .unique();
    if (existingGame) await ctx.db.replace(existingGame._id, gameRow);
    else await ctx.db.insert("games", gameRow);

    const old = await ctx.db
      .query("draftActions")
      .withIndex("by_gameId", (q) => q.eq("gameId", game.gameId))
      .collect();
    for (const row of old) await ctx.db.delete(row._id);
    for (const a of game.draft ?? []) {
      if (!a.hero) continue; // an unchecked game can still have a slot without a hero
      await ctx.db.insert("draftActions", {
        gameId: game.gameId,
        seriesId: series.seriesId,
        seq: a.seq,
        phase: a.phase,
        side: a.side,
        team: a.team,
        opponent: a.team === blueTeam ? redTeam : blueTeam,
        action: a.action,
        hero: a.hero,
        form: a.form ?? null,
        // Who played the hero, from the post-game screen. Null on bans.
        player: a.player ?? null,
        lane: a.lane ?? null,
        // The seat that made the pick on the draft bar. Differs from player after a swap.
        seatPlayer: a.preSwapPlayer ?? null,
        won: game.winner ? game.winner === a.team : null,
      });
    }
    return { gameId: game.gameId, actions: (game.draft ?? []).length };
  },
});

export const listSeries = query({
  args: {},
  handler: async (ctx) => ctx.db.query("series").withIndex("by_date").order("desc").collect(),
});

export const bySeries = query({
  args: { seriesId: v.string() },
  handler: async (ctx, { seriesId }) =>
    ctx.db.query("games").withIndex("by_seriesId", (q) => q.eq("seriesId", seriesId)).collect(),
});

/** The drafts of one match, game by game, for the draft board of the dashboard. */
export const drafts = query({
  args: { seriesId: v.string() },
  handler: async (ctx, { seriesId }) => {
    const rows = await ctx.db.query("games").withIndex("by_seriesId", (q) => q.eq("seriesId", seriesId)).collect();
    return rows
      .sort((a, b) => a.gameNo - b.gameNo)
      .map((row) => ({
        gameNo: row.gameNo,
        blue: row.blueTeam,
        red: row.redTeam,
        winner: row.winner ?? null,
        durationS: row.durationS ?? null,
        checked: row.checked ?? true,
        actions: ((row.data?.draft ?? []) as DraftAction[]).map((a) => ({
          seq: a.seq,
          order: a.order,
          side: a.side,
          team: a.team,
          action: a.action,
          hero: a.hero ?? null,
          player: a.player ?? null,
        })),
      }));
  },
});

/** Delete a game and its draft actions, for example after a wrong entry. Stored images stay. */
export const remove = mutation({
  args: { gameId: v.string() },
  handler: async (ctx, { gameId }) => {
    const g = await ctx.db.query("games").withIndex("by_gameId", (q) => q.eq("gameId", gameId)).unique();
    if (g) await ctx.db.delete(g._id);
    const acts = await ctx.db.query("draftActions").withIndex("by_gameId", (q) => q.eq("gameId", gameId)).collect();
    for (const a of acts) await ctx.db.delete(a._id);
    return { removed: !!g, actions: acts.length };
  },
});

async function dropImages(ctx: any, seriesId: string, gameNo?: number) {
  const rows = await ctx.db
    .query("images")
    .withIndex("by_game", (q: any) => (gameNo === undefined ? q.eq("seriesId", seriesId) : q.eq("seriesId", seriesId).eq("gameNo", gameNo)))
    .collect();
  for (const r of rows) {
    await ctx.storage.delete(r.storageId);
    await ctx.db.delete(r._id);
  }
  return rows.length;
}

async function dropGame(ctx: any, gameId: string) {
  const g = await ctx.db.query("games").withIndex("by_gameId", (q: any) => q.eq("gameId", gameId)).unique();
  if (g) await ctx.db.delete(g._id);
  const acts = await ctx.db.query("draftActions").withIndex("by_gameId", (q: any) => q.eq("gameId", gameId)).collect();
  for (const a of acts) await ctx.db.delete(a._id);
  return { removed: !!g, actions: acts.length };
}

/** Delete one game everywhere: the game row, its draft actions and its stored screenshots.
 *  `winner` is the series winner recomputed by the extractor after the delete. */
export const removeGame = mutation({
  args: { seriesId: v.string(), gameNo: v.number(), winner: v.optional(v.union(v.string(), v.null())) },
  handler: async (ctx, { seriesId, gameNo, winner }) => {
    const out = await dropGame(ctx, `${seriesId}_g${gameNo}`);
    const images = await dropImages(ctx, seriesId, gameNo);
    const series = await ctx.db.query("series").withIndex("by_seriesId", (q) => q.eq("seriesId", seriesId)).unique();
    let seriesRemoved = false;
    if (series) {
      const left = await ctx.db.query("games").withIndex("by_seriesId", (q) => q.eq("seriesId", seriesId)).collect();
      if (left.length === 0) {
        await ctx.db.delete(series._id);
        seriesRemoved = true;
      } else {
        await ctx.db.patch(series._id, { winner: winner ?? null, data: { ...series.data, winner: winner ?? null } });
      }
    }
    return { ...out, images, seriesRemoved };
  },
});

/** Delete a whole series: the series row, every game, every draft action and every stored screenshot. */
export const removeSeries = mutation({
  args: { seriesId: v.string() },
  handler: async (ctx, { seriesId }) => {
    const games = await ctx.db.query("games").withIndex("by_seriesId", (q) => q.eq("seriesId", seriesId)).collect();
    let actions = 0;
    for (const g of games) actions += (await dropGame(ctx, g.gameId)).actions;
    const images = await dropImages(ctx, seriesId);
    const series = await ctx.db.query("series").withIndex("by_seriesId", (q) => q.eq("seriesId", seriesId)).unique();
    if (series) await ctx.db.delete(series._id);
    return { removed: !!series, games: games.length, actions, images };
  },
});
