import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

const heroArg = v.object({
  heroId: v.string(),
  name: v.string(),
  forms: v.optional(v.array(v.string())),
  checked: v.boolean(),
  hasArt: v.boolean(),
  banArtId: v.optional(v.id("_storage")),
  pickArtId: v.optional(v.id("_storage")),
});

/** Replace the hero list with what the extractor holds. Ids missing from the payload are removed,
 *  and storage files that are no longer referenced are deleted. */
export const sync = mutation({
  args: { heroes: v.array(heroArg) },
  handler: async (ctx, { heroes }) => {
    const existing = await ctx.db.query("heroes").collect();
    const byId = new Map(existing.map((h) => [h.heroId, h]));
    let inserted = 0, updated = 0, removed = 0;
    const dropFile = async (id?: string, keep?: string) => { if (id && id !== keep) await ctx.storage.delete(id as any); };
    for (const h of heroes) {
      const cur = byId.get(h.heroId);
      if (cur) {
        await dropFile(cur.banArtId, h.banArtId);
        await dropFile(cur.pickArtId, h.pickArtId);
        await ctx.db.replace(cur._id, h); updated++; byId.delete(h.heroId);
      } else { await ctx.db.insert("heroes", h); inserted++; }
    }
    for (const stale of byId.values()) {
      await dropFile(stale.banArtId); await dropFile(stale.pickArtId);
      await ctx.db.delete(stale._id); removed++;
    }
    return { inserted, updated, removed };
  },
});

export const list = query({
  args: {},
  handler: async (ctx) => ctx.db.query("heroes").withIndex("by_heroId").collect(),
});

/** Heroes with signed image URLs, what a dashboard renders. */
export const listWithArt = query({
  args: {},
  handler: async (ctx) => {
    const rows = await ctx.db.query("heroes").withIndex("by_heroId").collect();
    return Promise.all(rows.map(async (h) => ({
      heroId: h.heroId,
      name: h.name,
      forms: h.forms ?? [],
      checked: h.checked,
      banArtUrl: h.banArtId ? await ctx.storage.getUrl(h.banArtId) : null,
      pickArtUrl: h.pickArtId ? await ctx.storage.getUrl(h.pickArtId) : null,
    })));
  },
});
