import { Link, createFileRoute, notFound } from '@tanstack/react-router'
import { useSuspenseQuery } from '@tanstack/react-query'
import { convexQuery } from '@convex-dev/react-query'
import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { api } from '@rov/backend/api'
import { STAGES, stageName } from '@rov/backend/ref'
import { plural } from '#/lib/format'
import { themeOf, themeVars } from '#/lib/teams'
import { HeroProvider } from '#/components/hero'
import { DotLegend, Empty, Section, TipProvider } from '#/components/ui'
import { Form, GameTime, Headline, Notice, Sides, Takeaways } from '#/components/overview'
import { MostPicked, PickedAgainst, Pools } from '#/components/picks'
import { Bans, Contested } from '#/components/bans'
import { Answers, Openers, PickOrder } from '#/components/draft'
import { PerGame, PlayersTable } from '#/components/players'
import { MatchList } from '#/components/matches'

// The address holds the choice, for example /teams/FS?stage=leg1.
// No `stage` means the default, an empty `stage` means all match types.
interface Search {
  stage?: string
}

const queries = (team: string, search: Search) => ({
  stats: convexQuery(api.stats.dashboard, { team, ...search }),
  heroes: convexQuery(api.heroes.listWithArt, {}),
  teams: convexQuery(api.teams.list, {}),
})

export const Route = createFileRoute('/teams/$teamId')({
  validateSearch: (raw: Record<string, unknown>): Search => (typeof raw.stage === 'string' ? { stage: raw.stage } : {}),
  loaderDeps: ({ search }) => search,
  // Fetch on the server first, so the page arrives with its numbers.
  loader: async ({ context, params, deps }) => {
    const q = queries(params.teamId, deps)
    const [, , teams] = await Promise.all([context.queryClient.ensureQueryData(q.stats), context.queryClient.ensureQueryData(q.heroes), context.queryClient.ensureQueryData(q.teams)])
    if (!teams.some((t) => t.teamId === params.teamId)) throw notFound()
  },
  component: TeamPage,
  notFoundComponent: () => (
    <main className="mx-auto max-w-[720px] px-6 py-24 text-center">
      <h1 className="text-xl font-semibold text-strong">No team with this id</h1>
      <p className="mt-2 text-muted">The teams of the league are listed on the league page.</p>
      <Link to="/" className="mt-5 inline-block text-strong underline underline-offset-4">Open the league page</Link>
    </main>
  ),
})

const SECTIONS = [
  { id: 'overview', name: 'Overview' },
  { id: 'picks', name: 'Picks' },
  { id: 'bans', name: 'Bans' },
  { id: 'draft', name: 'Draft' },
  { id: 'players', name: 'Players' },
  { id: 'matches', name: 'Matches' },
]

/** The section that is on screen now, so the section bar can mark it. */
function useActiveSection(): string {
  const [active, setActive] = useState(SECTIONS[0].id)
  useEffect(() => {
    // The last section whose top has passed a line a little below the sticky header.
    const update = () => {
      let current = SECTIONS[0].id
      for (const x of SECTIONS) {
        const el = document.getElementById(x.id)
        if (el && el.getBoundingClientRect().top <= 160) current = x.id
      }
      setActive(current)
    }
    update()
    window.addEventListener('scroll', update, { passive: true })
    return () => window.removeEventListener('scroll', update)
  }, [])
  return active
}

function TeamPage() {
  const { teamId } = Route.useParams()
  const search = Route.useSearch()
  const active = useActiveSection()
  const q = queries(teamId, search)
  // Convex keeps these live: a game pushed from the extractor shows up here without a reload.
  const { data: s } = useSuspenseQuery(q.stats)
  const { data: heroes } = useSuspenseQuery(q.heroes)
  const { data: teams } = useSuspenseQuery(q.teams)

  const teamName = (id: string) => teams.find((t) => t.teamId === id)?.name ?? id
  const stages = STAGES.filter((x) => s.options.stages[x.id])
  const c = s.coverage

  return (
    <div className="min-h-screen bg-bg" style={themeVars(teamId) as CSSProperties}>
      <HeroProvider heroes={heroes}>
        <TipProvider>
          <header className="sticky top-0 z-30 border-b border-line bg-bg/92 backdrop-blur">
            <div className="mx-auto flex h-14 max-w-[1280px] items-center gap-4 px-4 sm:px-7">
              <Link to="/" className="font-semibold tracking-tight text-strong hover:underline hover:underline-offset-4">RoV Draft Stats</Link>
              <span className="h-5 w-px bg-line-2" />
              <TeamSwitcher current={teamId} teams={teams} games={s.options.teams} />
              <span className="ml-auto hidden md:block"><DotLegend /></span>
            </div>
            <nav aria-label="Sections" className="mx-auto flex max-w-[1280px] gap-1 overflow-x-auto px-4 sm:px-7">
              {SECTIONS.map((x) => (
                <a
                  key={x.id}
                  href={`#${x.id}`}
                  aria-current={active === x.id ? 'true' : undefined}
                  className={`border-b-2 px-2.5 pt-1 pb-2.5 text-[13px] whitespace-nowrap hover:text-strong focus-visible:text-strong focus-visible:outline-none ${active === x.id ? 'border-accent text-strong' : 'border-transparent text-muted'}`}
                >
                  {x.name}
                </a>
              ))}
            </nav>
          </header>

          <main className="mx-auto flex max-w-[1280px] flex-col gap-12 px-4 pt-8 pb-24 sm:px-7">
            <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
              <div>
                <div className="mb-2 h-1 w-10 rounded-full bg-accent" />
                <h1 className="text-[34px] leading-tight font-semibold tracking-tight text-strong">{teamName(s.team)}</h1>
                <p className="mt-1 text-muted">
                  {s.stage ? stageName(s.stage) : 'All match types'} · {plural(c.matches, 'match', 'matches')} · {plural(c.games, 'game')}
                </p>
              </div>
              {stages.length > 1 ? (
                <div className="flex rounded-lg border border-line p-0.5" role="group" aria-label="Match type">
                  {[{ id: '', name: 'All' }, ...stages].map((x) => (
                    <Link
                      key={x.id}
                      to="/teams/$teamId"
                      params={{ teamId }}
                      search={{ stage: x.id }}
                      className={`rounded-md px-3 py-1 text-[13px] ${s.stage === x.id ? 'bg-accent font-medium text-accent-ink' : 'text-muted hover:text-strong'}`}
                    >
                      {x.name}
                    </Link>
                  ))}
                </div>
              ) : null}
            </div>

            {c.games ? (
              <>
                <Section id="overview" title="Overview">
                  <Notice coverage={c} />
                  <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
                    <Headline s={s} />
                    <Takeaways s={s} teamName={teamName} />
                  </div>
                  <Form s={s} teamName={teamName} />
                  <div className="grid gap-4 lg:grid-cols-2">
                    <Sides s={s} />
                    <GameTime s={s} />
                  </div>
                </Section>

                <Section id="picks" title="Picks">
                  <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
                    <MostPicked s={s} />
                    <PickedAgainst s={s} />
                  </div>
                  <Pools players={s.players} />
                </Section>

                <Section id="bans" title="Bans">
                  <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
                    <Bans s={s} team={s.team} />
                    <Contested s={s} />
                  </div>
                </Section>

                <Section id="draft" title="Draft">
                  <div className="grid items-start gap-4 xl:grid-cols-2">
                    <PickOrder s={s} />
                    <Answers s={s} />
                  </div>
                  <Openers s={s} />
                </Section>

                <Section id="players" title="Players">
                  <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,4fr)_minmax(0,8fr)]">
                    <PerGame s={s} team={s.team} />
                    <PlayersTable players={s.players} />
                  </div>
                </Section>

                <Section id="matches" title="Matches">
                  <MatchList matches={s.matches} team={s.team} teamName={teamName} />
                </Section>
              </>
            ) : (
              <Empty>No game of this team in this match type yet.</Empty>
            )}
          </main>
        </TipProvider>
      </HeroProvider>
    </div>
  )
}

/** The team on screen, and the list of every team of the league. */
function TeamSwitcher({ current, teams, games }: { current: string; teams: { teamId: string; name: string }[]; games: Record<string, number> }) {
  const teamName = (id: string) => teams.find((t) => t.teamId === id)?.name ?? id
  // Teams with games first, most games first, then the rest by name.
  const ids = [...teams].sort((a, b) => (games[b.teamId] ?? 0) - (games[a.teamId] ?? 0) || a.name.localeCompare(b.name)).map((t) => t.teamId)
  return (
    <details className="group relative">
      <summary className="flex h-8 cursor-pointer list-none items-center gap-2 rounded-md border border-line px-2.5 text-strong hover:border-line-2 focus-visible:border-accent focus-visible:outline-none [&::-webkit-details-marker]:hidden">
        <i className="size-2.5 rounded-full bg-accent" />
        <span className="font-medium">{teamName(current)}</span>
        <svg viewBox="0 0 16 16" className="size-3.5 text-muted transition-transform group-open:rotate-180" aria-hidden="true">
          <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </summary>
      <div className="absolute top-10 left-0 z-40 w-[270px] rounded-lg border border-line-2 bg-tip p-1.5 shadow-[0_16px_40px_rgb(0_0_0/0.6)]">
        <Link to="/" className="flex items-center gap-2.5 rounded-md px-2.5 py-2 hover:bg-panel-2">
          <i className="size-2.5 flex-none rounded-full bg-strong" />
          <span className="font-medium text-strong">League</span>
          <span className="ml-auto text-xs text-muted">standings, hero pool</span>
        </Link>
        <div className="my-1 h-px bg-line" />
        {ids.map((id) => (
          <Link
            key={id}
            to="/teams/$teamId"
            params={{ teamId: id }}
            className={`flex items-center gap-2.5 rounded-md px-2.5 py-2 hover:bg-panel-2 ${id === current ? 'bg-panel-2' : ''}`}
          >
            <i className="size-2.5 flex-none rounded-full" style={{ background: themeOf(id).accent }} />
            <span className="font-medium text-strong">{teamName(id)}</span>
            <span className="num ml-auto text-xs text-muted">{games[id] ? plural(games[id], 'game') : 'no game yet'}</span>
          </Link>
        ))}
      </div>
    </details>
  )
}
