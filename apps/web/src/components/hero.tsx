import { createContext, useContext, useMemo } from 'react'
import type { ReactNode } from 'react'

export interface HeroInfo {
  heroId: string
  name: string
  pickArtUrl: string | null
  banArtUrl: string | null
}

const HeroContext = createContext<Map<string, HeroInfo>>(new Map())

export function HeroProvider({ heroes, children }: { heroes: HeroInfo[]; children: ReactNode }) {
  const byId = useMemo(() => new Map(heroes.map((h) => [h.heroId, h])), [heroes])
  return <HeroContext.Provider value={byId}>{children}</HeroContext.Provider>
}

/** Look up the display name of a hero id. */
export function useHeroName(): (id: string) => string {
  const byId = useContext(HeroContext)
  return (id) => byId.get(id)?.name ?? id
}

const SIZES = { sm: 'size-[26px] rounded-[5px]', md: 'size-9 rounded-md', lg: 'size-12 rounded-lg' }

/** The picture of a hero. `muted` greys it out, for a ban. An empty id draws an empty slot. */
export function HeroFace({ id, size = 'sm', muted = false }: { id: string | null; size?: keyof typeof SIZES; muted?: boolean }) {
  const hero = useContext(HeroContext).get(id ?? '')
  const src = hero?.pickArtUrl ?? hero?.banArtUrl
  const box = `block flex-none bg-panel-3 ${SIZES[size]}`
  if (!src) return <i title={id ? (hero?.name ?? id) : 'No hero entered'} className={`${box} ${id ? '' : 'border border-dashed border-line-2 bg-transparent'}`} />
  return <img src={src} alt={hero?.name ?? ''} title={hero?.name} loading="lazy" className={`${box} object-cover object-[50%_16%] ${muted ? 'opacity-60 grayscale' : ''}`} />
}

/** A hero as a small picture and its name. */
export function Hero({ id }: { id: string }) {
  const name = useHeroName()(id)
  return (
    <span className="inline-flex max-w-full min-w-0 items-center gap-2.5 align-middle whitespace-nowrap text-strong">
      <HeroFace id={id} />
      <span className="overflow-hidden text-ellipsis">{name}</span>
    </span>
  )
}
