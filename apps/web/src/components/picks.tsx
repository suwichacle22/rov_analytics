import type { ReactNode } from 'react'
import { plural, record } from '#/lib/format'
import { laneName, whereLine } from '#/lib/stats'
import type { Dashboard, HeroRow, WhereKind } from '#/lib/stats'
import { Hero, HeroFace, useHeroName } from './hero'
import { Card, Dots, Empty, useFold, useTip } from './ui'

/** Names with how often each appears, most frequent first: "Overone ×4, Noarje". */
export function Counts({ of }: { of: Record<string, number> | undefined }) {
  const entries = Object.entries(of ?? {}).sort((a, b) => b[1] - a[1])
  if (!entries.length) return <>–</>
  return (
    <>
      {entries.map(([key, n], i) => (
        <span key={key}>
          {i ? ', ' : ''}
          {key}
          {n > 1 && entries.length > 1 ? <span className="num"> ×{n}</span> : null}
        </span>
      ))}
    </>
  )
}

interface Column {
  head: string
  className?: string
  cell: (row: HeroRow) => ReactNode
}

/** Heroes, one row each, with one mark per game. The marks are both the count and the record. */
export function HeroRows({ rows, kind, columns = [], limit = 10, empty = 'Nothing in these games yet.' }: { rows: HeroRow[]; kind: WhereKind; columns?: Column[]; limit?: number; empty?: string }) {
  const tip = useTip()
  const heroName = useHeroName()
  const { shown, more } = useFold(rows, limit)
  if (!rows.length) return <Empty>{empty}</Empty>
  return (
    <>
      <table className="tbl">
        <thead>
          <tr>
            <th>Hero</th>
            <th>Games</th>
            <th className="text-right">Won–lost</th>
            {columns.map((c) => <th key={c.head}>{c.head}</th>)}
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.hero} className="row-tip" {...tip({ title: heroName(r.hero), lines: r.where.map((w) => whereLine(w, kind)) })}>
              <td className="w-[1%] pr-5!"><Hero id={r.hero} /></td>
              <td><Dots results={r.where.map((w) => w.won)} /></td>
              <td className="num w-[1%] text-right text-muted">{record(r.wins, r.losses)}</td>
              {columns.map((c) => <td key={c.head} className={c.className}>{c.cell(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {more}
    </>
  )
}

export function MostPicked({ s }: { s: Dashboard }) {
  const columns: Column[] = [
    { head: 'Matches', className: 'num w-[1%] text-ink', cell: (r) => `${r.matches} of ${s.coverage.matches}` },
    { head: 'Played by', className: 'w-[1%] whitespace-nowrap text-muted', cell: (r) => <Counts of={r.players} /> },
  ]
  return (
    <Card title="Their picks">
      <HeroRows rows={s.picks} kind="pick" columns={columns} />
    </Card>
  )
}

export function PickedAgainst({ s }: { s: Dashboard }) {
  return (
    <Card title="Picked against them">
      <HeroRows rows={s.oppPicks} kind="opp" />
    </Card>
  )
}

/** What each player plays: the wider the grid, the deeper the pool. */
export function Pools({ players }: { players: Dashboard['players'] }) {
  const tip = useTip()
  const heroName = useHeroName()
  if (!players.length) return null
  return (
    <Card title="Hero pool of each player">
      <div className="grid grid-cols-1 gap-x-6 gap-y-7 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {players.map((p) => (
          <div key={p.player} className="min-w-0">
            <div className="mb-3 border-b border-line pb-2.5">
              <div className="text-[15px] font-semibold text-strong">{p.player}</div>
              <div className="text-xs text-muted">{laneName(p.lane)} · {plural(p.heroes.length, 'hero', 'heroes')}</div>
            </div>
            <div className="grid grid-cols-3 gap-x-2 gap-y-3.5">
              {p.heroes.map((h) => (
                <div
                  key={h.hero}
                  className="row-tip flex min-w-0 flex-col items-center gap-1.5 rounded-lg p-1"
                  {...tip({ title: `${p.player} on ${heroName(h.hero)} · ${record(h.wins, h.losses)}`, lines: h.where.map((w) => whereLine(w, 'plain')) })}
                >
                  <HeroFace id={h.hero} size="lg" />
                  <span className="max-w-full overflow-hidden text-[11px] leading-[1.3] text-ellipsis whitespace-nowrap text-ink">{heroName(h.hero)}</span>
                  <Dots results={h.where.map((w) => w.won)} size="sm" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}
