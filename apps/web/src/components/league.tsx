import type { CSSProperties, ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import type { FunctionReturnType } from 'convex/server'
import type { api } from '@rov/backend/api'
import { clock, plural, rate, record } from '#/lib/format'
import { themeOf, themeVars } from '#/lib/teams'
import { Hero, HeroFace, useHeroName } from './hero'
import { Card, Dot, Dots, Empty, useFold, useTip } from './ui'

export type League = FunctionReturnType<typeof api.stats.league>
type Standing = League['standings'][number]
type LeagueHero = League['heroes'][number]

const B = ({ children }: { children: ReactNode }) => <b className="font-semibold text-strong">{children}</b>

/** A few sentences about the league, written by rules with minimum counts. */
export function LeagueTakeaways({ s, teamName }: { s: League; teamName: (id: string) => string }) {
  const hero = useHeroName()
  const items: ReactNode[] = []
  const top = s.standings[0]
  if (top && top.matches.wins + top.matches.losses >= 3) {
    items.push(<><B>{teamName(top.team)}</B> leads with {record(top.matches.wins, top.matches.losses)} in matches and {record(top.games.wins, top.games.losses)} in games.</>)
  }
  const blue = s.sides.blue, all = blue.wins + blue.losses
  if (all >= 10 && Math.abs(blue.wins / all - 0.5) >= 0.1) {
    const side = blue.wins / all > 0.5 ? 'Blue' : 'Red'
    const w = side === 'Blue' ? blue.wins : blue.losses
    items.push(<><B>{side} side</B> wins {rate(w, all - w)} of games, {w} of {all}.</>)
  }
  const contested = s.heroes[0]
  if (contested && contested.presence >= 0.5) {
    items.push(<><B>{hero(contested.hero)}</B> is in {Math.round(100 * contested.presence)}% of drafts: picked {contested.picks} times and banned {contested.bans} times.</>)
  }
  const banned = [...s.heroes].sort((a, b) => b.bans - a.bans)[0]
  if (banned && banned.bans >= 5 && banned.hero !== contested?.hero) {
    items.push(<>The most banned hero is <B>{hero(banned.hero)}</B>, {banned.bans} times in {plural(s.coverage.games, 'game')}.</>)
  }
  const strong = s.heroes.filter((h) => h.wins + h.losses >= 8).sort((a, b) => b.wins / (b.wins + b.losses) - a.wins / (a.wins + a.losses))[0]
  if (strong && strong.wins / (strong.wins + strong.losses) >= 0.65) {
    items.push(<>The side that picks <B>{hero(strong.hero)}</B> wins {rate(strong.wins, strong.losses)}, {record(strong.wins, strong.losses)}.</>)
  }
  const weak = s.heroes.filter((h) => h.wins + h.losses >= 8).sort((a, b) => a.wins / (a.wins + a.losses) - b.wins / (b.wins + b.losses))[0]
  if (weak && weak.wins / (weak.wins + weak.losses) <= 0.35 && weak.hero !== strong?.hero) {
    items.push(<>The side that picks <B>{hero(weak.hero)}</B> loses more than it wins, {record(weak.wins, weak.losses)}.</>)
  }
  const first = [...s.heroes].sort((a, b) => b.first - a.first)[0]
  if (first && first.first >= 3) {
    items.push(<>The most common first pick is <B>{hero(first.hero)}</B>, {first.first} of {plural(s.coverage.games, 'game')}.</>)
  }
  const spread = s.standings.filter((t) => t.signature.length)
  if (spread.length >= 3) {
    items.push(<>{spread.length} teams have a signature hero, one they pick at least twice as often as the league does. See the table.</>)
  }
  return (
    <Card title="What stands out">
      {items.length ? (
        <ul className="flex flex-col gap-2.5">
          {items.slice(0, 6).map((item, i) => (
            <li key={i} className="flex gap-3 text-[14px] leading-snug text-ink">
              <i className="mt-[7px] block size-1.5 flex-none rounded-full bg-strong" />
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

/** The headline numbers of the league. */
export function LeagueHeadline({ s }: { s: League }) {
  const c = s.coverage
  const blue = s.sides.blue
  return (
    <Card>
      <div className="text-xs text-muted">Games played</div>
      <div className="mt-1 text-[64px] leading-none font-semibold tracking-tighter text-strong">{c.games}</div>
      <p className="mt-3 text-[15px] text-ink">
        in <B>{c.matches}</B> matches between <B>{s.standings.length}</B> teams
      </p>
      <p className="mt-0.5 text-muted">
        Blue side {record(blue.wins, blue.losses)} · average game {clock(s.avgDurationS)}
      </p>
    </Card>
  )
}

/** Every team, best record first. Dots are in the team's own colour. */
export function Standings({ s, teamName }: { s: League; teamName: (id: string) => string }) {
  const hero = useHeroName()
  const tip = useTip()
  if (!s.standings.length) return <Card title="Standings"><Empty>No game yet.</Empty></Card>
  return (
    <Card title="Standings">
      <div className="overflow-x-auto">
        <table className="tbl">
          <thead>
            <tr>
              <th className="w-[1%]">#</th>
              <th>Team</th>
              <th className="text-right">Matches</th>
              <th className="text-right">Games</th>
              <th className="text-right">Blue</th>
              <th className="text-right">Red</th>
              <th className="text-right">Avg time</th>
              <th>Every game</th>
              <th>Signature</th>
            </tr>
          </thead>
          <tbody>
            {s.standings.map((t, i) => (
              <tr key={t.team} style={themeVars(t.team) as CSSProperties}>
                <td className="num text-muted">{i + 1}</td>
                <td>
                  <Link to="/teams/$teamId" params={{ teamId: t.team }} className="inline-flex items-center gap-2.5 font-medium whitespace-nowrap text-strong hover:underline hover:underline-offset-4">
                    <i className="size-2.5 flex-none rounded-full" style={{ background: themeOf(t.team).accent }} />
                    {teamName(t.team)}
                  </Link>
                </td>
                <td className="num text-right text-strong">{record(t.matches.wins, t.matches.losses)}{t.matches.open ? <span className="text-muted"> +{t.matches.open}</span> : null}</td>
                <td className="num text-right">{record(t.games.wins, t.games.losses)}</td>
                <td className="num text-right text-muted">{record(t.sides.blue.wins, t.sides.blue.losses)}</td>
                <td className="num text-right text-muted">{record(t.sides.red.wins, t.sides.red.losses)}</td>
                <td className="num text-right text-muted">{clock(t.avgDurationS)}</td>
                <td>
                  <span className="inline-flex flex-wrap items-center gap-1">
                    {t.form.map((g) => <Dot key={`${g.seriesId}-${g.n}`} won={g.won} title={`vs ${g.opp} G${g.n} · ${g.won == null ? 'no winner' : g.won ? 'won' : 'lost'}`} />)}
                  </span>
                </td>
                <td>
                  <span className="inline-flex items-center gap-1.5">
                    {t.signature.map((x) => (
                      <span key={x.hero} className="row-tip rounded-md" {...tip({ title: `${teamName(t.team)} on ${hero(x.hero)}`, lines: [`${x.games} of ${plural(t.form.length, 'game')} · ${Math.round(100 * x.share)}%`, `league ${Math.round(100 * x.leagueShare)}% of games`] })}>
                        <HeroFace id={x.hero} />
                      </span>
                    ))}
                    {t.signature.length ? null : <span className="text-muted">–</span>}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

/** Blue side against red side over the whole league. */
export function LeagueSides({ s }: { s: League }) {
  const rows = [
    { name: 'Blue side', note: 'picks first', side: s.sides.blue },
    { name: 'Red side', note: 'picks last', side: s.sides.red },
  ]
  return (
    <Card title="By side">
      <div className="flex flex-col gap-5">
        {rows.map(({ name, note, side }) => (
          <div key={name}>
            <div className="flex items-baseline gap-2.5">
              <span className="text-[26px] leading-tight font-semibold tracking-tight text-strong">{record(side.wins, side.losses)}</span>
              <span className="font-medium text-ink">{name}</span>
              <span className="text-muted">{note} · {rate(side.wins, side.losses)}</span>
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

/** Every hero of the pool: how often it is in a draft, and how the side that picks it does. */
export function HeroPool({ s, teamName }: { s: League; teamName: (id: string) => string }) {
  const tip = useTip()
  const hero = useHeroName()
  const rows = s.heroes
  const { shown, more } = useFold(rows, 20)
  if (!rows.length) return null
  const max = Math.max(1, ...rows.map((r) => r.picks + r.bans))
  const lines = (r: LeagueHero) => [
    `picked ${r.picks}, banned ${r.bans} (${r.ban1} in the first phase, ${r.ban2} in the second)`,
    ...(r.first ? [`first pick of the game ${plural(r.first, 'time')}`] : []),
    ...Object.entries(r.teams).sort((a, b) => b[1] - a[1]).map(([t, n]) => `${teamName(t)} ×${n}`),
  ]
  return (
    <Card title="The hero pool">
      <table className="tbl">
        <thead>
          <tr>
            <th>Hero</th>
            <th>In the draft</th>
            <th className="text-right">Picked</th>
            <th className="text-right">Banned</th>
            <th>When picked</th>
            <th className="text-right">Won–lost</th>
            <th className="text-right">Teams</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.hero} className="row-tip" {...tip({ title: hero(r.hero), lines: lines(r) })}>
              <td className="w-[1%] pr-5!"><Hero id={r.hero} /></td>
              <td className="min-w-[160px]">
                <span className="flex items-center gap-2.5">
                  <span className="flex h-2.5 min-w-0 flex-1 gap-0.5">
                    {r.picks ? <i className={`block h-full bg-white/80 ${r.bans ? '' : 'rounded-r'}`} style={{ width: `${(100 * r.picks) / max}%` }} /> : null}
                    {r.bans ? <i className="block h-full rounded-r bg-white/30" style={{ width: `${(100 * r.bans) / max}%` }} /> : null}
                  </span>
                  <span className="num w-9 flex-none text-right text-strong">{Math.round(100 * r.presence)}%</span>
                </span>
              </td>
              <td className="num w-[1%] text-right">{r.picks}</td>
              <td className="num w-[1%] text-right">{r.bans}</td>
              <td className="w-[1%]"><Dots results={[...Array<boolean>(r.wins).fill(true), ...Array<boolean>(r.losses).fill(false)]} size="sm" /></td>
              <td className="num w-[1%] text-right text-muted">{r.wins + r.losses ? `${record(r.wins, r.losses)} · ${rate(r.wins, r.losses)}` : '–'}</td>
              <td className="num w-[1%] text-right text-muted">{Object.keys(r.teams).length || '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {more}
      <p className="mt-3.5 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-2.5 w-5 rounded-sm bg-white/80" />picked</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-2.5 w-5 rounded-sm bg-white/30" />banned</span>
        <span className="inline-flex items-center gap-1.5"><Dot won size="sm" />the picking side won</span>
        <span className="inline-flex items-center gap-1.5"><Dot won={false} size="sm" />it lost</span>
      </p>
    </Card>
  )
}

/** The teams as cards that open their dashboards. */
export function TeamCards({ s, teamName }: { s: League; teamName: (id: string) => string }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {s.standings.map((t: Standing) => (
        <Link
          key={t.team}
          to="/teams/$teamId"
          params={{ teamId: t.team }}
          style={themeVars(t.team) as CSSProperties}
          className="group rounded-xl border border-line bg-panel p-4 hover:border-line-2 hover:bg-panel-2 focus-visible:border-accent focus-visible:outline-none"
        >
          <div className="mb-2 h-1 w-8 rounded-full bg-accent" />
          <div className="flex items-baseline justify-between gap-3">
            <span className="font-semibold text-strong">{teamName(t.team)}</span>
            <span className="num text-muted">{record(t.matches.wins, t.matches.losses)}</span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1">{t.form.map((g) => <Dot key={`${g.seriesId}-${g.n}`} won={g.won} size="sm" />)}</div>
        </Link>
      ))}
    </div>
  )
}
