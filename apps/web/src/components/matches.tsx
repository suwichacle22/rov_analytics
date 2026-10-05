import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { convexQuery } from '@convex-dev/react-query'
import type { FunctionReturnType } from 'convex/server'
import { api } from '@rov/backend/api'
import { clock, record } from '#/lib/format'
import { shortDate } from '#/lib/stats'
import type { Match } from '#/lib/stats'
import { HeroFace } from './hero'
import { Card, Dot } from './ui'

type Game = FunctionReturnType<typeof api.games.drafts>[number]
type Action = Game['actions'][number]

/** One team's half of a draft: its bans greyed out, then its picks, each in the order it was made. */
function DraftRow({ name, side, actions, mine }: { name: string; side: string; actions: Action[]; mine: boolean }) {
  const of = (kind: string) => actions.filter((a) => a.action === kind).sort((a, b) => a.order - b.order)
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
      <div className="w-[92px] flex-none">
        <div className={`font-semibold ${mine ? 'text-accent' : 'text-strong'}`}>{name}</div>
        <div className="text-[11px] text-muted">{side} side</div>
      </div>
      <div className="flex items-center gap-1.5" aria-label={`${name} bans`}>
        <span className="mr-0.5 text-[10.5px] tracking-wide text-muted uppercase">Bans</span>
        {of('ban').map((a) => <HeroFace key={a.seq} id={a.hero} muted />)}
      </div>
      <div className="flex items-start gap-2" aria-label={`${name} picks`}>
        <span className="mt-2.5 mr-0.5 text-[10.5px] tracking-wide text-muted uppercase">Picks</span>
        {of('pick').map((a) => (
          <span key={a.seq} className="flex flex-col items-center gap-1" title={a.player ? `Played by ${a.player}` : undefined}>
            <HeroFace id={a.hero} size="md" />
            <span className="num text-[10px] leading-none text-muted">{a.order}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

/** The drafts of one match, loaded when the match is opened. */
function DraftBoards({ match, team }: { match: Match; team: string }) {
  const { data, isPending, error } = useQuery(convexQuery(api.games.drafts, { seriesId: match.seriesId }))
  if (isPending) return <p className="px-1 py-3 text-muted">Loading the drafts…</p>
  if (error || !data) return <p className="px-1 py-3 text-muted">The drafts could not be loaded.</p>
  return (
    <div className="flex flex-col gap-3 pt-1 pb-3">
      {data.map((g) => {
        const won = g.winner ? g.winner === team : null
        const opp = g.blue === team ? g.red : g.blue
        const sideOf = (t: string) => (g.blue === t ? 'Blue' : 'Red')
        const rows = g.blue === team ? [team, opp] : [opp, team] // blue side first, it picks first
        return (
          <div key={g.gameNo} className="rounded-lg border border-line bg-panel px-4 py-3.5">
            <div className="mb-3 flex items-center gap-2.5">
              <Dot won={won} />
              <span className="font-semibold text-strong">Game {g.gameNo}</span>
              <span className="text-muted">{won == null ? 'no winner entered' : won ? 'won' : 'lost'} · {clock(g.durationS)}{g.checked ? '' : ' · not checked yet'}</span>
            </div>
            <div className="flex flex-col gap-3.5">
              {rows.map((t) => <DraftRow key={t} name={t} side={sideOf(t)} mine={t === team} actions={g.actions.filter((a) => a.team === t)} />)}
            </div>
          </div>
        )
      })}
      <p className="px-1 text-xs text-muted">The number under a pick is its place in the draft, 1 to 10. Bans are greyed out.</p>
    </div>
  )
}

/** Every match as a row that opens to show its drafts. */
export function MatchList({ matches, team, teamName }: { matches: Match[]; team: string; teamName: (id: string) => string }) {
  const [open, setOpen] = useState<string | null>(null)
  return (
    <Card>
      {[...matches].reverse().map((m) => {
        const isOpen = open === m.seriesId
        return (
          <div key={m.seriesId} className="border-t border-line first:border-t-0">
            <button
              type="button"
              aria-expanded={isOpen}
              onClick={() => setOpen(isOpen ? null : m.seriesId)}
              className="row-tip grid w-full cursor-pointer grid-cols-[64px_minmax(0,1fr)_auto_auto_16px] items-center gap-4 rounded-md px-1 py-2.5 text-left"
            >
              <span className="num text-muted">{shortDate(m.date)}</span>
              <span className="overflow-hidden font-medium text-ellipsis whitespace-nowrap text-strong">{teamName(m.opp)}</span>
              <span className="flex gap-1.5">{m.games.map((g) => <Dot key={g.n} won={g.won} title={`Game ${g.n} · ${g.side} side · ${clock(g.durationS)}`} />)}</span>
              <span className="num w-[68px] text-right">
                <span className={m.won ? 'font-medium text-strong' : 'text-muted'}>{m.won == null ? 'Open' : m.won ? 'Won' : 'Lost'}</span> {record(m.wins, m.losses)}
              </span>
              <svg viewBox="0 0 16 16" className={`size-4 text-muted transition-transform ${isOpen ? 'rotate-180' : ''}`} aria-hidden="true">
                <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            {isOpen ? <DraftBoards match={m} team={team} /> : null}
          </div>
        )
      })}
    </Card>
  )
}
