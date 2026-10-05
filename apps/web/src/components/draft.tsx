import { LANES } from '@rov/backend/ref'
import { plural, record } from '#/lib/format'
import { laneName, whereLine } from '#/lib/stats'
import type { Dashboard, HeroRow } from '#/lib/stats'
import { Hero, useHeroName } from './hero'
import { Card, Dots, Empty, useFold, useTip } from './ui'

const ORDINAL = ['1st', '2nd', '3rd', '4th', '5th']

/** In which of its five picks the team takes each position. */
export function PickOrder({ s }: { s: Dashboard }) {
  // Convex returns object keys in alphabetical order, so the lane order comes from the shared list.
  const lanes = LANES.filter((l) => l in s.laneOrder)
  const max = Math.max(1, ...lanes.flatMap((l) => s.laneOrder[l]))
  const total = lanes.reduce((n, l) => n + s.laneOrder[l].reduce((a, b) => a + b, 0), 0)
  if (!total) {
    return <Card title="Which position they pick when"><Empty>No pick has a position yet. Set the positions on the Teams page of the extractor.</Empty></Card>
  }
  // The usual order: take the strongest cell, then the strongest among the lanes and picks left.
  const usual: (string | null)[] = [null, null, null, null, null]
  const left = new Set<string>(lanes)
  for (let n = 0; n < 5; n++) {
    let best: { lane: string; col: number; v: number } | null = null
    for (const lane of left) for (let col = 0; col < 5; col++) {
      if (usual[col] === null && (!best || s.laneOrder[lane][col] > best.v)) best = { lane, col, v: s.laneOrder[lane][col] }
    }
    if (!best) break
    usual[best.col] = best.lane
    left.delete(best.lane)
  }
  return (
    <Card title="Which position they pick when">
      <table className="w-full border-separate border-spacing-1">
        <thead>
          <tr>
            <th />
            {ORDINAL.map((o) => <th key={o} className="px-1.5 pb-1 text-center text-[11.5px] font-medium text-muted">{o} pick</th>)}
          </tr>
        </thead>
        <tbody>
          {lanes.map((lane) => (
            <tr key={lane}>
              <th scope="row" className="w-px pr-3 text-left text-xs font-medium whitespace-nowrap text-ink">{laneName(lane)}</th>
              {s.laneOrder[lane].map((v, i) => {
                const a = v / max
                return (
                  <td
                    key={i}
                    title={`${laneName(lane)} was the ${ORDINAL[i]} pick in ${plural(v, 'game')}`}
                    className={`num h-10 min-w-11 rounded-md text-center text-[13px] font-medium ${a > 0.6 ? 'text-accent-ink' : 'text-strong'}`}
                    style={{ background: v ? `color-mix(in oklab, var(--color-accent) ${Math.round(12 + 88 * a)}%, transparent)` : 'rgb(255 255 255 / 0.03)' }}
                  >
                    {v || ''}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3.5 text-xs text-muted">
        The usual order:{' '}
        {usual.map((lane, i) => (
          <span key={i} className="text-ink">
            {i ? <span className="text-muted">, then </span> : null}
            {laneName(lane)}
          </span>
        ))}
        .
      </p>
    </Card>
  )
}

function OpenerList({ title, rows, kind }: { title: string; rows: HeroRow[]; kind: 'pick' | 'opp' }) {
  const tip = useTip()
  const heroName = useHeroName()
  return (
    <div className="min-w-0">
      <h4 className="mb-2 text-xs font-medium text-muted">{title}</h4>
      {rows.length ? (
        <div>
          {rows.slice(0, 6).map((r) => (
            <div key={r.hero} className="row-tip flex items-center justify-between gap-3 border-t border-line py-1.5" {...tip({ title: heroName(r.hero), lines: r.where.map((w) => whereLine(w, kind)) })}>
              <Hero id={r.hero} />
              <Dots results={r.where.map((w) => w.won)} />
            </div>
          ))}
          {rows.length > 6 ? <p className="border-t border-line pt-2 text-xs text-muted">and {rows.length - 6} more, once each</p> : null}
        </div>
      ) : (
        <Empty>None yet.</Empty>
      )}
    </div>
  )
}

/** How drafts open: the first pick on blue side, the answer on red side. */
export function Openers({ s }: { s: Dashboard }) {
  const blue = s.record.sides.blue.games, red = s.record.sides.red.games
  return (
    <Card title="How their drafts open">
      <div className="grid gap-x-8 gap-y-6 md:grid-cols-3">
        <OpenerList title={`First pick on blue side · ${plural(blue, 'game')}`} rows={s.openers.blue} kind="pick" />
        <OpenerList title={`First two picks on red side · ${plural(red, 'game')}`} rows={s.openers.red} kind="pick" />
        <OpenerList title={`Opponent's first pick · ${plural(red, 'game')}`} rows={s.openers.faced} kind="opp" />
      </div>
    </Card>
  )
}

/** When the opponent picked X, the team picked Y in its next turn. */
export function Answers({ s }: { s: Dashboard }) {
  const { shown, more } = useFold(s.answers, 7)
  if (!s.answers.length) return <Card title="Answers to an opponent pick"><Empty>No pair has come up twice yet.</Empty></Card>
  return (
    <Card title="Answers to an opponent pick">
      <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_56px] gap-x-3 pb-1.5 text-[11.5px] font-medium text-muted">
        <span>Opponent picked</span><span /><span>They picked</span><span className="text-right">Games</span>
      </div>
      {shown.map((a) => (
        <div key={`${a.after}>${a.then}`} className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_56px] items-center gap-x-3 border-t border-line py-1.5">
          <Hero id={a.after} />
          <span className="text-xs text-muted">then</span>
          <Hero id={a.then} />
          <span className="flex justify-end" title={`${plural(a.games, 'game')}, ${record(a.wins, a.games - a.wins)}`}>
            <Dots results={[...Array<boolean>(a.wins).fill(true), ...Array<boolean>(a.games - a.wins).fill(false)]} />
          </span>
        </div>
      ))}
      {more}
    </Card>
  )
}
