import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

/** Step 1 of an upload: the extractor POSTs the image bytes to this URL. */
export const generateUploadUrl = mutation({
  args: {},
  handler: async (ctx) => ctx.storage.generateUploadUrl(),
});

/** Step 2: record which game the stored file belongs to. Replaces an older file for the same slot. */
export const saveImage = mutation({
  args: {
    seriesId: v.string(),
    gameNo: v.number(),
    kind: v.string(),
    name: v.string(),
    storageId: v.id("_storage"),
    size: v.optional(v.number()),
    contentType: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("images")
      .withIndex("by_game", (q) => q.eq("seriesId", args.seriesId).eq("gameNo", args.gameNo).eq("kind", args.kind))
      .unique();
    if (existing) {
      if (existing.storageId !== args.storageId) await ctx.storage.delete(existing.storageId);
      await ctx.db.replace(existing._id, args);
      return existing._id;
    }
    return ctx.db.insert("images", args);
  },
});

/** Signed URL for a stored image, used when the local copy is gone. */
export const imageUrl = query({
  args: { seriesId: v.string(), gameNo: v.number(), kind: v.string() },
  handler: async (ctx, { seriesId, gameNo, kind }) => {
    const row = await ctx.db
      .query("images")
      .withIndex("by_game", (q) => q.eq("seriesId", seriesId).eq("gameNo", gameNo).eq("kind", kind))
      .unique();
    if (!row) return null;
    return { name: row.name, storageId: row.storageId, url: await ctx.storage.getUrl(row.storageId) };
  },
});

export const listImages = query({
  args: { seriesId: v.string() },
  handler: async (ctx, { seriesId }) => {
    const rows = await ctx.db.query("images").collect();
    return rows
      .filter((r) => r.seriesId === seriesId)
      .map(({ seriesId, gameNo, kind, name, storageId, size }) => ({ seriesId, gameNo, kind, name, storageId, size }));
  },
});
