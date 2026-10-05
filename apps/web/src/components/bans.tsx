import { whereLine } from '#/lib/stats'
import type { Dashboard, HeroRow } from '#/lib/stats'
import { Hero, useHeroName } from './hero'
import { Card, Empty, useFold, useTip } from './ui'

interface BanSide {
  first: number
  second: number
  row?: HeroRow
}
const side = (row: HeroRow | undefined): BanSide => ({ first: row?.phases?.ban1 ?? 0, second: row?.phases?.ban2 ?? 0, row })

/** One bar that grows away from the hero in the middle: first ban phase nearest, second phase after it. */
function Bar({ value, max, mine, mirror }: { value: BanSide; max: number; mine: boolean; mirror: boolean }) {
  const total = value.first + value.second
  const seg = (n: number, solid: boolean, end: boolean) =>
    n ? (
      <i
        className={`block h-2.5 ${mine ? (solid ? 'bg-accent' : 'bg-accent/45') : solid ? 'bg-white/70' : 'bg-white/30'} ${end ? (mirror ? 'rounded-l' : 'rounded-r') : ''}`}
        style={{ flex: n }}
      />
    ) : null
  // The bar starts at the hero and the number sits at its tip, on both sides.
  return (
    <div className={`flex items-center gap-2 ${mirror ? 'flex-row-reverse' : ''}`}>
      {total ? (
        <div className={`flex gap-0.5 ${mirror ? 'flex-row-reverse' : ''}`} style={{ width: `calc((100% - 28px) * ${total / max})` }}>
          {seg(value.first, true, !value.second)}
          {seg(value.second, false, true)}
        </div>
      ) : null}
      <span className={`num w-5 flex-none ${mirror ? 'text-right' : ''} ${total ? 'text-strong' : 'text-muted'}`}>{total || '–'}</span>
    </div>
  )
}

/** Bans by the team on the left, bans against the team on the right, the hero between them. */
export function Bans({ s, team }: { s: Dashboard; team: string }) {
  const tip = useTip()
  const heroName = useHeroName()
  const by = new Map(s.bans.map((r) => [r.hero, r])), vs = new Map(s.bansAgainst.map((r) => [r.hero, r]))
  const rows = [...new Set([...by.keys(), ...vs.keys()])]
    .map((hero) => ({ hero, by: side(by.get(hero)), vs: side(vs.get(hero)) }))
    .map((r) => ({ ...r, byTotal: r.by.first + r.by.second, vsTotal: r.vs.first + r.vs.second }))
    .sort((a, b) => b.byTotal + b.vsTotal - (a.byTotal + a.vsTotal) || b.vsTotal - a.vsTotal || a.hero.localeCompare(b.hero))
  const { shown, more } = useFold(rows, 12)
  if (!rows.length) return <Card title="Bans"><Empty>No bans in these games yet.</Empty></Card>
  const max = Math.max(...rows.map((r) => Math.max(r.byTotal, r.vsTotal)))
  return (
    <Card title="Bans">
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(120px,170px)_minmax(0,1fr)] items-center gap-x-4 text-[11.5px] font-medium text-muted">
        <div className="text-right">Banned by {team}</div>
        <div />
        <div>Banned against {team}</div>
      </div>
      <div className="mt-2">
        {shown.map((r) => (
          <div
            key={r.hero}
            className="row-tip grid grid-cols-[minmax(0,1fr)_minmax(120px,170px)_minmax(0,1fr)] items-center gap-x-4 border-t border-line py-1.5"
            {...tip({
              title: heroName(r.hero),
              lines: [
                ...(r.by.row?.where ?? []).map((w) => `${team} banned · ${whereLine(w, 'ban')}`),
                ...(r.vs.row?.where ?? []).map((w) => `banned against · ${whereLine(w, 'ban')}`),
              ],
            })}
          >
            <Bar value={r.by} max={max} mine mirror />
            <Hero id={r.hero} />
            <Bar value={r.vs} max={max} mine={false} mirror={false} />
          </div>
        ))}
      </div>
      {more}
      <p className="mt-3.5 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-2.5 w-5 rounded-sm bg-accent" />by {team}</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-2.5 w-5 rounded-sm bg-white/70" />against {team}</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-sm bg-white/70" /><i className="inline-block h-2.5 w-2.5 rounded-sm bg-white/30" />solid is the first ban phase, lighter is the second</span>
      </p>
    </Card>
  )
}

/** The heroes both teams fight over: picked or banned, as a share of all games. */
export function Contested({ s }: { s: Dashboard }) {
  const heroName = useHeroName()
  const rows = s.meta.slice(0, 12)
  if (!rows.length) return null
  const max = Math.max(1, ...rows.map((r) => r.picks + r.bans))
  return (
    <Card title="Most contested heroes">
      <table className="tbl">
        <thead>
          <tr><th>Hero</th><th>In the draft</th><th className="text-right">Picked</th><th className="text-right">Banned</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.hero} title={`${heroName(r.hero)}: picked ${r.teamPicks} by the team and ${r.oppPicks} by opponents, banned ${r.teamBans} by the team and ${r.oppBans} by opponents`}>
              <td className="w-[1%] pr-5!"><Hero id={r.hero} /></td>
              <td>
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
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3.5 flex gap-5 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-2.5 w-5 rounded-sm bg-white/80" />picked</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-2.5 w-5 rounded-sm bg-white/30" />banned</span>
      </p>
    </Card>
  )
}
