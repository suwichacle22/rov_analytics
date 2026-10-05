import { useLayoutEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { convexQuery } from '@convex-dev/react-query'
import type { FunctionReturnType } from 'convex/server'
import { api } from '@rov/backend/api'
import { clock, record } from '#/lib/format'
import { shortDate } from '#/lib/stats'
import type { Match } from '#/lib/stats'
import { HeroFace } from './hero'
import { Dot } from './ui'

type Game = FunctionReturnType<typeof api.games.drafts>[number]
type Action = Game['actions'][number]

/** Where on screen the hovered match sits. */
export interface Anchor {
  left: number
  top: number
  bottom: number
}

/** One side of a draft in the order of the broadcast bar: blue fills its slots left to right, red
 *  right to left, so red is drawn in reverse. Bans sit on the outside, small and greyed out. */
function Side({ name, side, actions, mine }: { name: string; side: 'blue' | 'red'; actions: Action[]; mine: boolean }) {
  const of = (kind: string) => actions.filter((a) => a.action === kind).sort((a, b) => (side === 'blue' ? a.order - b.order : b.order - a.order))
  const red = side === 'red'
  return (
    <div className={`flex flex-col gap-1 ${red ? 'items-end' : 'items-start'}`}>
      <div className="flex items-baseline gap-1.5 text-[11px] leading-none">
        <span className={`font-semibold ${mine ? 'text-accent' : 'text-strong'}`}>{name}</span>
        <span className="text-muted">{side}</span>
      </div>
      <div className={`flex items-center gap-2.5 ${red ? 'flex-row-reverse' : ''}`}>
        <div className="flex gap-0.5">{of('ban').map((a) => <HeroFace key={a.seq} id={a.hero} muted />)}</div>
        <div className="flex gap-1">{of('pick').map((a) => <HeroFace key={a.seq} id={a.hero} size="md" />)}</div>
      </div>
    </div>
  )
}

/** The drafts of one match in a box beside the pointer: every game, blue side left, red side right. */
export function MatchPeek({ match, team, teamName, anchor }: { match: Match; team: string; teamName: (id: string) => string; anchor: Anchor }) {
  const ref = useRef<HTMLDivElement>(null)
  const { data, isPending, error } = useQuery(convexQuery(api.games.drafts, { seriesId: match.seriesId }))
  // Under the match when there is room, above it otherwise, and never outside the window.
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const below = anchor.bottom + 8, above = anchor.top - r.height - 8
    const top = below + r.height <= window.innerHeight - 8 ? below : Math.max(8, above)
    el.style.left = `${Math.max(8, Math.min(anchor.left, window.innerWidth - r.width - 8))}px`
    el.style.top = `${top}px`
  })
  return (
    <div ref={ref} role="tooltip" className="pointer-events-none fixed z-50 rounded-xl border border-line-2 bg-tip p-4 shadow-[0_16px_40px_rgb(0_0_0/0.6)]">
      <div className="mb-3 flex items-baseline gap-2">
        <b className="font-semibold text-strong">vs {teamName(match.opp)}</b>
        <span className="text-xs text-muted">{shortDate(match.date)} · {match.won == null ? 'open' : match.won ? 'won' : 'lost'} {record(match.wins, match.losses)}</span>
      </div>
      {isPending ? <p className="text-muted">Loading the drafts…</p> : null}
      {error ? <p className="text-muted">The drafts could not be loaded.</p> : null}
      <div className="flex flex-col gap-2.5">
        {(data ?? []).map((g) => {
          const won = g.winner ? g.winner === team : null
          return (
            <div key={g.gameNo} className="flex items-end gap-4 border-t border-line pt-2.5 first:border-t-0 first:pt-0">
              <div className="w-[58px] flex-none pb-0.5 text-xs leading-tight">
                <div className="flex items-center gap-1.5 font-semibold text-strong"><Dot won={won} />G{g.gameNo}</div>
                <div className="num mt-1 text-muted">{won == null ? 'open' : won ? 'won' : 'lost'} {clock(g.durationS)}</div>
              </div>
              <Side name={g.blue} side="blue" mine={g.blue === team} actions={g.actions.filter((a) => a.team === g.blue)} />
              <Side name={g.red} side="red" mine={g.red === team} actions={g.actions.filter((a) => a.team === g.red)} />
            </div>
          )
        })}
      </div>
      <p className="mt-3 text-[11px] text-muted">Picks stand as on the broadcast bar. The small grey ones are the bans.</p>
    </div>
  )
}
