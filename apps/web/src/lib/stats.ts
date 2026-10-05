import type { FunctionReturnType } from 'convex/server'
import type { api } from '@rov/backend/api'
import { LANE_NAMES } from '@rov/backend/ref'
import type { Lane } from '@rov/backend/ref'

// The types come straight from the backend function, so a change there shows up here as a type error.
export type Dashboard = FunctionReturnType<typeof api.stats.dashboard>
export type HeroRow = Dashboard['picks'][number]
export type Where = HeroRow['where'][number]
export type Match = Dashboard['matches'][number]

export type WhereKind = 'pick' | 'opp' | 'ban' | 'plain'

/** One game behind a count, as a line of the tooltip. */
export function whereLine(w: Where, kind: WhereKind): string {
  const bits = [`vs ${w.opp} G${w.n}`, w.won == null ? '' : w.won ? 'won' : 'lost']
  if (kind === 'pick' || kind === 'opp') bits.push(w.player ?? '', w.order ? `pick ${w.order}` : '')
  if (kind === 'ban') bits.push(w.phase === 'ban1' ? 'first ban phase' : 'second ban phase')
  return bits.filter(Boolean).join(' · ')
}

export const laneName = (lane: string | null): string => (lane ? (LANE_NAMES[lane as Lane] ?? lane) : 'no position set')

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-08-22" as "22 Aug". */
export function shortDate(iso: string): string {
  const [, m, d] = iso.split('-').map(Number)
  return m && d ? `${d} ${MONTHS[m - 1]}` : iso
}
