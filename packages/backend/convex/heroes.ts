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
  banArtName: v.optional(v.string()),
  pickArtName: v.optional(v.string()),
});

const cropArg = v.object({
  heroId: v.string(),
  kind: v.string(),
  name: v.string(),
  storageId: v.id("_storage"),
  size: v.number(),
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

const cropKey = (c: { kind: string; heroId: string; name: string }) => `${c.kind}/${c.heroId}/${c.name}`;

/** Add or replace learned crops. Crops that are not in the payload stay: an extractor on a fresh
 *  machine holds none, and must not empty the table by saying so. */
export const addCrops = mutation({
  args: { crops: v.array(cropArg) },
  handler: async (ctx, { crops }) => {
    const byKey = new Map((await ctx.db.query("heroCrops").collect()).map((c) => [cropKey(c), c]));
    let inserted = 0, updated = 0;
    for (const c of crops) {
      const cur = byKey.get(cropKey(c));
      if (!cur) { await ctx.db.insert("heroCrops", c); inserted++; }
      else if (cur.storageId !== c.storageId) {
        await ctx.storage.delete(cur.storageId);
        await ctx.db.replace(cur._id, c); updated++;
      }
    }
    return { inserted, updated };
  },
});

/** Remove crops the user deleted, together with their stored files. */
export const removeCrops = mutation({
  args: { crops: v.array(v.object({ heroId: v.string(), kind: v.string(), name: v.string() })) },
  handler: async (ctx, { crops }) => {
    const gone = new Set(crops.map(cropKey));
    let removed = 0;
    for (const c of await ctx.db.query("heroCrops").collect()) {
      if (!gone.has(cropKey(c))) continue;
      await ctx.storage.delete(c.storageId);
      await ctx.db.delete(c._id); removed++;
    }
    return { removed };
  },
});

/** Everything an extractor needs to rebuild its hero folder on another machine: the list, the art
 *  and the learned crops, each file with a download URL. */
export const mirror = query({
  args: {},
  handler: async (ctx) => {
    const heroes = await ctx.db.query("heroes").withIndex("by_heroId").collect();
    const crops = await ctx.db.query("heroCrops").collect();
    return {
      heroes: await Promise.all(heroes.map(async (h) => ({
        heroId: h.heroId,
        name: h.name,
        forms: h.forms ?? [],
        checked: h.checked,
        banArtId: h.banArtId ?? null,
        pickArtId: h.pickArtId ?? null,
        banArtName: h.banArtName ?? null,
        pickArtName: h.pickArtName ?? null,
        banArtUrl: h.banArtId ? await ctx.storage.getUrl(h.banArtId) : null,
        pickArtUrl: h.pickArtId ? await ctx.storage.getUrl(h.pickArtId) : null,
      }))),
      crops: await Promise.all(crops.map(async (c) => ({
        heroId: c.heroId,
        kind: c.kind,
        name: c.name,
        storageId: c.storageId,
        size: c.size,
        url: await ctx.storage.getUrl(c.storageId),
      }))),
    };
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
