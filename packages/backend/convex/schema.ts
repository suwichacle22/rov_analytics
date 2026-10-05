import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

// Mirrors the extractor's JSON. `data` holds the full record so nothing is lost;
// the indexed columns are what the dashboard filters on.
export default defineSchema({
  series: defineTable({
    seriesId: v.string(),
    tournament: v.string(),
    stage: v.string(),
    bestOf: v.number(),
    date: v.string(),
    teamA: v.string(),
    teamB: v.string(),
    homeTeam: v.string(),
    winner: v.optional(v.union(v.string(), v.null())),
    vodUrl: v.optional(v.union(v.string(), v.null())), // source link of the match
    data: v.any(),
  })
    .index("by_seriesId", ["seriesId"])
    .index("by_tournament", ["tournament"])
    .index("by_date", ["date"]),

  games: defineTable({
    gameId: v.string(),
    seriesId: v.string(),
    gameNo: v.number(),
    blueTeam: v.string(),
    redTeam: v.string(),
    winner: v.optional(v.union(v.string(), v.null())),
    durationS: v.optional(v.union(v.number(), v.null())),
    patch: v.optional(v.union(v.string(), v.null())),
    savedAt: v.optional(v.string()),
    // False for a game that was pushed as a draft, before it was checked and saved in the extractor.
    // Missing on rows from before this column existed; those were all saved games.
    checked: v.optional(v.boolean()),
    data: v.any(),
  })
    .index("by_gameId", ["gameId"])
    .index("by_seriesId", ["seriesId"])
    .index("by_blueTeam", ["blueTeam"])
    .index("by_redTeam", ["redTeam"]),

  // One row per draft action so first pick, most banned and response picks are plain queries.
  draftActions: defineTable({
    gameId: v.string(),
    seriesId: v.string(),
    seq: v.number(),
    phase: v.string(), // "ban1" | "pick1" | "ban2" | "pick2"
    side: v.string(),
    team: v.string(),
    opponent: v.string(),
    action: v.string(),
    hero: v.string(),
    form: v.optional(v.union(v.string(), v.null())),
    player: v.optional(v.union(v.string(), v.null())), // who played the hero (post-game screen)
    lane: v.optional(v.union(v.string(), v.null())),
    seatPlayer: v.optional(v.union(v.string(), v.null())), // seat that made the pick (draft bar)
    won: v.optional(v.union(v.boolean(), v.null())),
  })
    .index("by_gameId", ["gameId"])
    .index("by_team_hero", ["team", "hero"])
    .index("by_hero", ["hero"])
    .index("by_team_action", ["team", "action"])
    .index("by_player", ["player"]),

  // Team names, mirrored from data/ref/teams.json by `rov-extract push`.
  teams: defineTable({
    teamId: v.string(),
    name: v.string(),
  }).index("by_teamId", ["teamId"]),

  // Hero reference, mirrored from data/ref/heroes.json on every Save of the Heroes page.
  heroes: defineTable({
    heroId: v.string(),
    name: v.string(),
    forms: v.optional(v.array(v.string())),
    checked: v.boolean(),
    hasArt: v.boolean(),
    banArtId: v.optional(v.id("_storage")),
    pickArtId: v.optional(v.id("_storage")),
    // File name of the art in data/ref/art, or "crop/<file>" when a learned crop stands in for it.
    banArtName: v.optional(v.string()),
    pickArtName: v.optional(v.string()),
  }).index("by_heroId", ["heroId"]),

  // Crops of a hero learned from broadcasts, mirrored from data/ref/crops. Together with the art
  // above they let an extractor on another machine fetch everything it recognises heroes with.
  heroCrops: defineTable({
    heroId: v.string(),
    kind: v.string(), // "ban" | "pick"
    name: v.string(),
    storageId: v.id("_storage"),
    size: v.number(),
  }).index("by_hero", ["heroId", "kind"]),

  // Screenshots attached in the extractor. The file itself lives in Convex storage.
  images: defineTable({
    seriesId: v.string(),
    gameNo: v.number(),
    kind: v.string(), // "draft" | "post"
    name: v.string(),
    storageId: v.id("_storage"),
    size: v.optional(v.number()),
    contentType: v.optional(v.string()),
  }).index("by_game", ["seriesId", "gameNo", "kind"]),

  // The working files of the extractor, so every machine that runs it holds the same matches:
  // series.json, the form of each game (g1.draft.json), its Recognise reading (g1.proposal.json)
  // and the saved game (g1.json). `folder` is the match id, or "_ref" for reference lists.
  // The row is small on purpose: the extractor lists all of them to see what changed. The text
  // of a file is in extractorBodies.
  extractorFiles: defineTable({
    folder: v.string(),
    name: v.string(),
    hash: v.string(),
    size: v.number(),
    updatedAt: v.number(), // when the file was last written on the machine that sent it, in ms
  }).index("by_file", ["folder", "name"]),

  extractorBodies: defineTable({
    folder: v.string(),
    name: v.string(),
    content: v.string(), // the JSON text
  }).index("by_file", ["folder", "name"]),
});
