import { mutation, query, type MutationCtx } from "./_generated/server";
import { v } from "convex/values";

// The extractor keeps its matches as JSON files on the machine it runs on. These functions hold a
// copy of every such file, and `rov_extractor/sync.py` keeps the two in step, so a second machine
// gets the same matches without any file being carried over by hand.

const fileRef = { folder: v.string(), name: v.string() };

/** Every file with its hash, without the text. The extractor compares this with its own folder. */
export const index = query({
  args: {},
  handler: async (ctx) =>
    (await ctx.db.query("extractorFiles").collect()).map(({ folder, name, hash, updatedAt }) => ({ folder, name, hash, updatedAt })),
});

/** The text of the named files of one folder. */
export const bodies = query({
  args: { folder: v.string(), names: v.array(v.string()) },
  handler: async (ctx, { folder, names }) => {
    const out: { name: string; content: string }[] = [];
    for (const name of names) {
      const row = await ctx.db.query("extractorBodies").withIndex("by_file", (q) => q.eq("folder", folder).eq("name", name)).unique();
      if (row) out.push({ name, content: row.content });
    }
    return out;
  },
});

/** Store files, replacing the ones already there under the same name. */
export const put = mutation({
  args: {
    files: v.array(v.object({ ...fileRef, hash: v.string(), size: v.number(), updatedAt: v.number(), content: v.string() })),
  },
  handler: async (ctx, { files }) => {
    for (const { content, ...meta } of files) {
      const at = (q: any) => q.eq("folder", meta.folder).eq("name", meta.name);
      const row = await ctx.db.query("extractorFiles").withIndex("by_file", at).unique();
      if (row) await ctx.db.replace(row._id, meta);
      else await ctx.db.insert("extractorFiles", meta);
      const body = await ctx.db.query("extractorBodies").withIndex("by_file", at).unique();
      if (body) await ctx.db.replace(body._id, { folder: meta.folder, name: meta.name, content });
      else await ctx.db.insert("extractorBodies", { folder: meta.folder, name: meta.name, content });
    }
    return { stored: files.length };
  },
});

/** Remove files that were deleted in the extractor. */
export const remove = mutation({
  args: { files: v.array(v.object(fileRef)) },
  handler: async (ctx, { files }) => {
    let removed = 0;
    for (const f of files) {
      const at = (q: any) => q.eq("folder", f.folder).eq("name", f.name);
      for (const table of ["extractorFiles", "extractorBodies"] as const) {
        const row = await ctx.db.query(table).withIndex("by_file", at).unique();
        if (row) { await ctx.db.delete(row._id); removed++; }
      }
    }
    return { removed };
  },
});

/** Remove every file of one match. Called when the match itself is deleted. */
export async function dropFolder(ctx: MutationCtx, folder: string) {
  let removed = 0;
  for (const table of ["extractorFiles", "extractorBodies"] as const) {
    const rows = await ctx.db.query(table).withIndex("by_file", (q) => q.eq("folder", folder)).collect();
    for (const r of rows) { await ctx.db.delete(r._id); removed++; }
  }
  return removed;
}
