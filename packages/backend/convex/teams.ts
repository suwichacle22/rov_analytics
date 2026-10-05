import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

/** Replace the team list with what the extractor holds in data/ref/teams.json. */
export const sync = mutation({
  args: { teams: v.array(v.object({ teamId: v.string(), name: v.string() })) },
  handler: async (ctx, { teams }) => {
    const existing = await ctx.db.query("teams").collect();
    const byId = new Map(existing.map((t) => [t.teamId, t]));
    for (const t of teams) {
      const cur = byId.get(t.teamId);
      if (cur) await ctx.db.replace(cur._id, t);
      else await ctx.db.insert("teams", t);
      byId.delete(t.teamId);
    }
    for (const stale of byId.values()) await ctx.db.delete(stale._id);
    return { teams: teams.length, removed: byId.size };
  },
});

export const list = query({
  args: {},
  handler: async (ctx) => {
    const rows = await ctx.db.query("teams").withIndex("by_teamId").collect();
    return rows.map((t) => ({ teamId: t.teamId, name: t.name }));
  },
});
