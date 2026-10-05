import { Link, createFileRoute } from '@tanstack/react-router'
import { useSuspenseQuery } from '@tanstack/react-query'
import { convexQuery } from '@convex-dev/react-query'
import { api } from '@rov/backend/api'
import { STAGES, stageName } from '@rov/backend/ref'
import { plural } from '#/lib/format'
import { HeroProvider } from '#/components/hero'
import { DotLegend, Empty, Section, TipProvider } from '#/components/ui'
import { Notice } from '#/components/overview'
import { HeroPool, LeagueHeadline, LeagueSides, LeagueTakeaways, Standings, TeamCards } from '#/components/league'

// The league page. /?stage=leg1 chooses a match type; an empty stage means all of them.
interface Search {
  stage?: string
}

const queries = (search: Search) => ({
  league: convexQuery(api.stats.league, { ...search }),
  heroes: convexQuery(api.heroes.listWithArt, {}),
  teams: convexQuery(api.teams.list, {}),
})

export const Route = createFileRoute('/')({
  validateSearch: (raw: Record<string, unknown>): Search => (typeof raw.stage === 'string' ? { stage: raw.stage } : {}),
  loaderDeps: ({ search }) => search,
  loader: async ({ context, deps }) => {
    const q = queries(deps)
    await Promise.all([context.queryClient.ensureQueryData(q.league), context.queryClient.ensureQueryData(q.heroes), context.queryClient.ensureQueryData(q.teams)])
  },
  component: LeaguePage,
})

function LeaguePage() {
  const search = Route.useSearch()
  const q = queries(search)
  const { data: s } = useSuspenseQuery(q.league)
  const { data: heroes } = useSuspenseQuery(q.heroes)
  const { data: teams } = useSuspenseQuery(q.teams)
  const teamName = (id: string) => teams.find((t) => t.teamId === id)?.name ?? id
  const stages = STAGES.filter((x) => s.options.stages[x.id])
  const c = s.coverage

  return (
    <div className="min-h-screen bg-bg">
      <HeroProvider heroes={heroes}>
        <TipProvider>
          <header className="sticky top-0 z-30 border-b border-line bg-bg/92 backdrop-blur">
            <div className="mx-auto flex h-14 max-w-[1280px] items-center gap-4 px-4 sm:px-7">
              <span className="font-semibold tracking-tight text-strong">RoV Draft Stats</span>
              <span className="h-5 w-px bg-line-2" />
              <span className="text-muted">League</span>
              <span className="ml-auto hidden md:block"><DotLegend subject="the side" /></span>
            </div>
          </header>

          <main className="mx-auto flex max-w-[1280px] flex-col gap-12 px-4 pt-8 pb-24 sm:px-7">
            <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
              <div>
                <div className="mb-2 h-1 w-10 rounded-full bg-strong" />
                <h1 className="text-[34px] leading-tight font-semibold tracking-tight text-strong">RoV Pro League 2026 Winter</h1>
                <p className="mt-1 text-muted">
                  {s.stage ? stageName(s.stage) : 'All match types'} · {plural(c.matches, 'match', 'matches')} · {plural(c.games, 'game')}
                </p>
              </div>
              {stages.length > 1 ? (
                <div className="flex rounded-lg border border-line p-0.5" role="group" aria-label="Match type">
                  {[{ id: '', name: 'All' }, ...stages].map((x) => (
                    <Link key={x.id} to="/" search={{ stage: x.id }} className={`rounded-md px-3 py-1 text-[13px] ${s.stage === x.id ? 'bg-strong font-medium text-bg' : 'text-muted hover:text-strong'}`}>
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
                    <LeagueHeadline s={s} />
                    <LeagueTakeaways s={s} teamName={teamName} />
                  </div>
                </Section>

                <Section id="teams" title="Teams">
                  <TeamCards s={s} teamName={teamName} />
                  <Standings s={s} teamName={teamName} />
                  <LeagueSides s={s} />
                </Section>

                <Section id="heroes" title="Heroes">
                  <HeroPool s={s} teamName={teamName} />
                </Section>
              </>
            ) : (
              <Empty>No game in this match type yet.</Empty>
            )}
          </main>
        </TipProvider>
      </HeroProvider>
    </div>
  )
}
