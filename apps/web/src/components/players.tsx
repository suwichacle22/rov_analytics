import { num } from '#/lib/format'
import type { Dashboard } from '#/lib/stats'
import { Card } from './ui'

const STATS = [
  { key: 'kills', name: 'Kills' },
  { key: 'towers', name: 'Towers' },
  { key: 'dragons', name: 'Dragons' },
  { key: 'slayers', name: 'Dark Slayers' },
] as const

/** Per-game averages of the team beside those of its opponents. Each row has its own scale. */
export function PerGame({ s, team }: { s: Dashboard; team: string }) {
  const gold = s.totals.team.gold, goldOpp = s.totals.opp.gold
  return (
    <Card title="An average game">
      <div className="flex flex-col gap-4">
        {STATS.map(({ key, name }) => {
          const a = s.totals.team[key], b = s.totals.opp[key]
          const max = Math.max(a.avg ?? 0, b.avg ?? 0, 0.1)
          const bar = (v: number | null, mine: boolean, label: string) => (
            <div className="flex items-center gap-2.5">
              <span className="w-[72px] flex-none text-xs text-muted">{label}</span>
              <span className="flex h-2.5 min-w-0 flex-1">
                <i className={`block h-full rounded-r ${mine ? 'bg-accent' : 'bg-white/35'}`} style={{ width: `${(100 * (v ?? 0)) / max}%` }} />
              </span>
              <span className="num w-9 flex-none text-right text-strong">{v == null ? '–' : v.toFixed(1)}</span>
            </div>
          )
          return (
            <div key={key}>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="font-medium text-ink">{name}</span>
                <span className="text-[11px] text-muted">read in {Math.min(a.games, b.games)} games</span>
              </div>
              {bar(a.avg, true, team)}
              {bar(b.avg, false, 'Opponents')}
            </div>
          )
        })}
        <p className="border-t border-line pt-3 text-muted">
          Gold: <span className="num text-strong">{gold.avg == null ? '–' : num(Math.round(gold.avg))}</span> for {team}, <span className="num text-strong">{goldOpp.avg == null ? '–' : num(Math.round(goldOpp.avg))}</span> for opponents.
        </p>
      </div>
    </Card>
  )
}

export function PlayersTable({ players }: { players: Dashboard['players'] }) {
  if (!players.length) return null
  return (
    <Card title="Player averages">
      <div className="overflow-x-auto">
        <table className="tbl">
          <thead>
            <tr>
              <th>Player</th><th>Position</th><th className="text-right">Heroes</th><th className="text-right">K / D / A</th><th className="text-right">KDA</th>
              <th className="text-right">Damage dealt</th><th className="text-right">Damage taken</th><th className="text-right">Games read</th>
            </tr>
          </thead>
          <tbody>
            {players.map((p) => {
              const g = p.kdaGames
              const per = (v: number) => (g ? (v / g).toFixed(1) : '–')
              return (
                <tr key={p.player}>
                  <td><b className="font-semibold text-strong">{p.player}</b></td>
                  <td className="text-muted">{p.lane ?? '–'}</td>
                  <td className="num text-right">{p.heroes.length}</td>
                  <td className="num text-right">{per(p.kills)} / {per(p.deaths)} / {per(p.assists)}</td>
                  <td className="num text-right">{g ? ((p.kills + p.assists) / Math.max(1, p.deaths)).toFixed(1) : '–'}</td>
                  <td className="num text-right">{num(p.avgDmgDealt)}</td>
                  <td className="num text-right">{num(p.avgDmgTaken)}</td>
                  <td className="num text-right text-muted">{g} of {p.games}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
