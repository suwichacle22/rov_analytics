/* eslint-disable */
/**
 * Generated `api` utility.
 *
 * THIS CODE IS AUTOMATICALLY GENERATED.
 *
 * To regenerate, run `npx convex dev`.
 * @module
 */

import type * as files from "../files.js";
import type * as games from "../games.js";
import type * as heroes from "../heroes.js";
import type * as lib_leagueStats from "../lib/leagueStats.js";
import type * as lib_ref from "../lib/ref.js";
import type * as lib_teamStats from "../lib/teamStats.js";
import type * as stats from "../stats.js";
import type * as teams from "../teams.js";

import type {
  ApiFromModules,
  FilterApi,
  FunctionReference,
} from "convex/server";

declare const fullApi: ApiFromModules<{
  files: typeof files;
  games: typeof games;
  heroes: typeof heroes;
  "lib/leagueStats": typeof lib_leagueStats;
  "lib/ref": typeof lib_ref;
  "lib/teamStats": typeof lib_teamStats;
  stats: typeof stats;
  teams: typeof teams;
}>;

/**
 * A utility for referencing Convex functions in your app's public API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = api.myModule.myFunction;
 * ```
 */
export declare const api: FilterApi<
  typeof fullApi,
  FunctionReference<any, "public">
>;

/**
 * A utility for referencing Convex functions in your app's internal API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = internal.myModule.myFunction;
 * ```
 */
export declare const internal: FilterApi<
  typeof fullApi,
  FunctionReference<any, "internal">
>;

export declare const components: {};
