import { useState } from 'react'
import type { ReactNode } from 'react'
import { LANES } from '@rov/backend/ref'
import { clock, plural, rate, record } from '#/lib/format'
import { laneName, shortDate } from '#/lib/stats'
import type { Dashboard } from '#/lib/stats'
import { useHeroName } from './hero'
import { MatchPeek } from './peek'
import type { Anchor } from './peek'
import { Card, Dot, DotLegend, Dots } from './ui'

/** The one number the page leads with. */
export function Headline({ s }: { s: Dashboard }) {
  const { games, matches } = s.record
  return (
    <Card>
      <div className="text-xs text-muted">Games won</div>
      <div className="mt-1 text-[64px] leading-none font-semibold tracking-tighter text-strong">{rate(games.wins, games.losses)}</div>
      <p className="mt-3 text-[15px] text-ink">
        <b className="font-semibold text-strong">{games.wins}</b> won and <b className="font-semibold text-strong">{games.losses}</b> lost in {plural(games.wins + games.losses, 'game')}
      </p>
      <p className="mt-0.5 text-muted">
        {plural(matches.wins, 'match', 'matches')} won, {matches.losses} lost
        {matches.open ? `, ${matches.open} not decided in the data` : ''}
      </p>
    </Card>
  )
}

/** A few sentences that say what the numbers below add up to. */
export function Takeaways({ s, teamName }: { s: Dashboard; teamName: (id: string) => string }) {
  const hero = useHeroName()
  const B = ({ children }: { children: ReactNode }) => <b className="font-semibold text-strong">{children}</b>
  const list = (names: string[]) => (names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : (names[0] ?? ''))
  const items: ReactNode[] = []
  const games = s.coverage.games
  const { blue, red } = s.record.sides

  // Which side suits the team, when both were played enough and the gap is clear.
  if (blue.games >= 3 && red.games >= 3) {
    const b = blue.wins / Math.max(1, blue.wins + blue.losses), r = red.wins / Math.max(1, red.wins + red.losses)
    if (Math.abs(b - r) >= 0.15) {
      const [good, bad, goodName, badName] = b > r ? [blue, red, 'blue', 'red'] : [red, blue, 'red', 'blue']
      items.push(<>Much stronger on <B>{goodName} side</B>: {record(good.wins, good.losses)} there, against {record(bad.wins, bad.losses)} on {badName} side.</>)
    }
  }
  const top = s.meta[0]
  if (top && top.presence >= 0.6) {
    items.push(<><B>{hero(top.hero)}</B> is in {top.presence >= 1 ? 'every draft' : `${Math.round(100 * top.presence)}% of drafts`}: picked {top.picks} times and banned {top.bans} times.</>)
  }
  const mostPicked = s.picks.filter((p) => p.games === s.picks[0]?.games)
  if (mostPicked.length && mostPicked.length <= 3 && mostPicked[0].games >= 3) {
    items.push(<>Most picked: <B>{list(mostPicked.map((p) => hero(p.hero)))}</B>, in {mostPicked[0].matches} of {s.coverage.matches} matches{mostPicked.length > 1 ? ' each' : ''}.</>)
  }
  const unbeaten = s.picks.filter((p) => p.games >= 3 && p.losses === 0 && p.wins === p.games).slice(0, 3)
  if (unbeaten.length) {
    items.push(<>Unbeaten on <B>{list(unbeaten.map((p) => hero(p.hero)))}</B>: {unbeaten.map((p) => record(p.wins, 0)).join(', ')}.</>)
  }
  const target = s.bansAgainst[0]
  if (target && target.games >= Math.max(3, games * 0.3)) {
    items.push(<>Opponents ban <B>{hero(target.hero)}</B> against them in {target.games} of {plural(games, 'game')}.</>)
  }
  const lanes = LANES.filter((l) => l in s.laneOrder)
  const most = (col: number) => lanes.reduce((best, l) => (s.laneOrder[l][col] > s.laneOrder[best][col] ? l : best), lanes[0])
  if (lanes.length && s.laneOrder[most(0)][0] >= games * 0.35 && s.laneOrder[most(4)][4] >= games * 0.35) {
    items.push(<>They usually pick <B>{laneName(most(0))}</B> first ({s.laneOrder[most(0)][0]} of {games}) and <B>{laneName(most(4))}</B> last ({s.laneOrder[most(4)][4]} of {games}).</>)
  }
  const trouble = s.oppPicks.filter((p) => p.games >= 4 && p.losses > p.wins)[0]
  if (trouble) {
    items.push(<>They lose more than they win when the opponent has <B>{hero(trouble.hero)}</B>: {record(trouble.wins, trouble.losses)}.</>)
  }
  if (s.record.matches.losses === 1) {
    const lost = s.matches.find((m) => m.won === false)
    if (lost) items.push(<>The only lost match is against <B>{teamName(lost.opp)}</B>, {record(lost.wins, lost.losses)}.</>)
  }

  return (
    <Card title="What stands out">
      {items.length ? (
        <ul className="flex flex-col gap-2.5">
          {items.slice(0, 6).map((item, i) => (
            <li key={i} className="flex gap-3 text-[14px] leading-snug text-ink">
              <i className="mt-[7px] block size-1.5 flex-none rounded-full bg-accent" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted">Not enough games yet to say anything with confidence.</p>
      )}
    </Card>
  )
}

/** Every game as one mark, in the order it was played, grouped by match. A match shows its drafts
 *  while the pointer is on it, or while it has the keyboard focus. */
export function Form({ s, teamName }: { s: Dashboard; teamName: (id: string) => string }) {
  const [peek, setPeek] = useState<{ seriesId: string; anchor: Anchor } | null>(null)
  const show = (seriesId: string) => (e: { currentTarget: HTMLElement }) => {
    const r = e.currentTarget.getBoundingClientRect()
    setPeek({ seriesId, anchor: { left: r.left, top: r.top, bottom: r.bottom } })
  }
  const hide = () => setPeek(null)
  const open = peek ? s.matches.find((m) => m.seriesId === peek.seriesId) : null
  return (
    <Card title="Every game, in order">
      <div className="flex flex-wrap gap-y-5">
        {s.matches.map((m) => (
          <div
            key={m.seriesId}
            tabIndex={0}
            onMouseEnter={show(m.seriesId)}
            onMouseLeave={hide}
            onFocus={show(m.seriesId)}
            onBlur={hide}
            className="flex min-w-[112px] cursor-default flex-col gap-2 border-l border-line px-4 py-1 outline-none first:border-l-0 first:pl-0 hover:bg-panel-2 focus-visible:bg-panel-2"
          >
            <div className="flex items-baseline gap-2">
              <span className="font-semibold text-strong">{m.opp}</span>
              <span className="text-xs text-muted">{shortDate(m.date)}</span>
            </div>
            <div className="flex gap-2">
              {m.games.map((g) => (
                <span key={g.n} className="flex flex-col items-center gap-1">
                  <Dot won={g.won} size="lg" />
                  <span className="text-[10px] leading-none text-muted">{g.side === 'blue' ? 'B' : 'R'}</span>
                </span>
              ))}
            </div>
            <div className="num text-xs text-muted">
              <span className={m.won ? 'font-medium text-strong' : ''}>{m.won == null ? 'Open' : m.won ? 'Won' : 'Lost'}</span> {record(m.wins, m.losses)}
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3.5 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-muted">
        <DotLegend />
        <span>B blue side · R red side</span>
      </p>
      {peek && open ? <MatchPeek match={open} team={s.team} teamName={teamName} anchor={peek.anchor} /> : null}
    </Card>
  )
}

/** Blue side against red side: the record and one mark per game, in rows that line up. */
export function Sides({ s }: { s: Dashboard }) {
  const rows = [
    { name: 'Blue side', note: 'picks first', side: s.record.sides.blue },
    { name: 'Red side', note: 'picks last', side: s.record.sides.red },
  ]
  return (
    <Card title="By side">
      <div className="flex flex-col gap-5">
        {rows.map(({ name, note, side }) => (
          <div key={name}>
            <div className="flex items-baseline gap-2.5">
              <span className="text-[26px] leading-tight font-semibold tracking-tight text-strong">{record(side.wins, side.losses)}</span>
              <span className="font-medium text-ink">{name}</span>
              <span className="text-muted">{note} · {rate(side.wins, side.losses)} of {plural(side.games, 'game')}</span>
            </div>
            <div className="mt-2">
              <Dots results={[...Array<boolean>(side.wins).fill(true), ...Array<boolean>(side.losses).fill(false)]} />
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

/** How long the games lasted: one mark per game, stacked in two-minute steps. */
export function GameTime({ s }: { s: Dashboard }) {
  const games = s.matches.flatMap((m) => m.games).filter((g) => g.durationS)
  const r = s.record
  if (!games.length) return <Card><div className="text-xs text-muted">Game time</div><p className="mt-2 text-muted">No game time entered yet.</p></Card>
  const STEP = 120
  const bin = (sec: number) => Math.floor(sec / STEP)
  const first = Math.min(...games.map((g) => bin(g.durationS!))), last = Math.max(...games.map((g) => bin(g.durationS!)))
  const bins = Array.from({ length: last - first + 1 }, (_, i) => games.filter((g) => bin(g.durationS!) === first + i))
  return (
    <Card>
      <div className="text-xs text-muted">Game time</div>
      <div className="mt-1 flex items-baseline gap-2.5">
        <span className="text-[30px] leading-tight font-semibold tracking-tight text-strong">{clock(r.avgDurationS)}</span>
        <span className="text-muted">on average · wins {clock(r.avgWinS)} · losses {clock(r.avgLossS)}</span>
      </div>
      <div className="mt-3 flex items-end gap-1" role="img" aria-label="Game length of every game in two-minute steps">
        {bins.map((col, i) => (
          <div key={i} className="flex min-w-0 flex-1 flex-col items-center gap-1">
            <div className="flex flex-col-reverse items-center gap-[3px]">
              {col.map((g, j) => <Dot key={j} won={g.won} title={`${clock(g.durationS)} · ${g.won ? 'won' : 'lost'}`} />)}
            </div>
            <div className="h-px w-full bg-line-2" />
            <div className="num h-3 text-[10px] leading-none text-muted">{i % 2 === 0 ? (first + i) * (STEP / 60) : ''}</div>
          </div>
        ))}
      </div>
      <div className="mt-1 text-[10px] text-muted">minutes</div>
    </Card>
  )
}

/** Says how much of the data is still unchecked, so nobody reads a single number as fact. */
export function Notice({ coverage: c }: { coverage: Dashboard['coverage'] }) {
  const open = c.games - c.checked
  const parts: string[] = []
  if (open) parts.push(`${open} of ${plural(c.games, 'game')} ${open === 1 ? 'comes' : 'come'} straight from Recognise and ${open === 1 ? 'is' : 'are'} not checked yet, so a single number can be wrong.`)
  if (c.unnamed) parts.push(`${plural(c.unnamed, 'draft slot')} of ${c.slots} ${c.unnamed === 1 ? 'has' : 'have'} no hero and ${c.unnamed === 1 ? 'is' : 'are'} left out.`)
  if (c.noWinner) parts.push(`${plural(c.noWinner, 'game')} ${c.noWinner === 1 ? 'has' : 'have'} no winner.`)
  if (!parts.length) return null
  return (
    <p className="flex max-w-[110ch] gap-3 rounded-lg border border-line px-3.5 py-2.5 text-muted">
      <span className="flex-none self-start rounded border border-line-2 px-1.5 text-[10.5px] leading-5 font-medium tracking-wide text-ink uppercase">Unchecked data</span>
      <span>{parts.join(' ')}</span>
    </p>
  )
}
