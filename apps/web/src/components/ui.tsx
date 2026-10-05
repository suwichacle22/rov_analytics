import { createContext, useCallback, useContext, useLayoutEffect, useRef, useState } from 'react'
import type { FocusEvent, MouseEvent, ReactNode } from 'react'

/** A page section with an anchor for the section bar. */
export function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-28 pt-2">
      <h2 className="mb-4 text-lg font-semibold tracking-tight text-strong">{title}</h2>
      <div className="flex flex-col gap-4">{children}</div>
    </section>
  )
}

/** A box that holds one chart or table. A title stands alone: no line of explanation under it. */
export function Card({ title, children, className = '' }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <div className={`min-w-0 rounded-xl border border-line bg-panel p-5 ${className}`}>
      {title ? <h3 className="mb-3.5 text-sm font-semibold text-strong">{title}</h3> : null}
      {children}
    </div>
  )
}

export const Empty = ({ children }: { children: ReactNode }) => <p className="my-1 text-muted">{children}</p>

// ---- one game as one mark

type Result = boolean | null

/** One game: filled in the team colour when the team won, a hollow ring when it lost. */
export function Dot({ won, title, size = 'md' }: { won: Result; title?: string; size?: 'sm' | 'md' | 'lg' }) {
  const box = size === 'lg' ? 'size-3.5' : size === 'sm' ? 'size-1.5' : 'size-2.5'
  const look = won === true ? 'bg-accent' : won === false ? `${size === 'sm' ? 'border' : 'border-[1.5px]'} border-white/45` : 'bg-white/15'
  return <i title={title} className={`inline-block flex-none rounded-full ${box} ${look}`} />
}

/** A row of games. The length is the number of games, the fill is how they went. */
export function Dots({ results, size = 'md' }: { results: Result[]; size?: 'sm' | 'md' }) {
  return (
    <span className={`inline-flex flex-wrap items-center ${size === 'sm' ? 'gap-0.5' : 'gap-1'}`}>
      {results.map((won, i) => <Dot key={i} won={won} size={size} />)}
    </span>
  )
}

/** Explains the dots. Shown once near the top and again where a chart needs it. */
export function DotLegend({ subject = 'the team' }: { subject?: string }) {
  return (
    <span className="inline-flex items-center gap-3.5 text-xs text-muted">
      <span className="inline-flex items-center gap-1.5"><Dot won />{subject} won</span>
      <span className="inline-flex items-center gap-1.5"><Dot won={false} />{subject} lost</span>
    </span>
  )
}

/** Rows past `limit` stay folded behind a button. */
export function useFold<T>(rows: T[], limit: number): { shown: T[]; more: ReactNode } {
  const [all, setAll] = useState(false)
  const folded = rows.length > limit && !all
  return {
    shown: folded ? rows.slice(0, limit) : rows,
    more: folded ? (
      <button
        type="button"
        onClick={() => setAll(true)}
        className="mt-3 inline-flex h-7 cursor-pointer items-center rounded-md border border-line px-2.5 text-xs font-medium text-ink hover:border-line-2 hover:bg-panel-2 focus-visible:border-accent focus-visible:outline-none"
      >
        Show all {rows.length}
      </button>
    ) : null,
  }
}

// ---- tooltip: the games behind a row, on hover and on keyboard focus

interface TipData {
  title: string
  lines: string[]
}
interface TipState extends TipData {
  x: number
  y: number
}
type Bind = (data: TipData) => {
  tabIndex: number
  onMouseMove: (e: MouseEvent<HTMLElement>) => void
  onMouseLeave: () => void
  onFocus: (e: FocusEvent<HTMLElement>) => void
  onBlur: () => void
}

const TipContext = createContext<Bind | null>(null)

/** Props that make an element show a tooltip. Spread them on the element. */
export function useTip(): Bind {
  const bind = useContext(TipContext)
  if (!bind) throw new Error('useTip needs a TipProvider above it')
  return bind
}

export function TipProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<TipState | null>(null)
  const bind = useCallback<Bind>(
    (data) => ({
      tabIndex: 0,
      onMouseMove: (e) => setTip({ ...data, x: e.clientX, y: e.clientY }),
      onMouseLeave: () => setTip(null),
      onFocus: (e) => {
        const r = e.currentTarget.getBoundingClientRect()
        setTip({ ...data, x: r.left + 40, y: r.bottom - 8 })
      },
      onBlur: () => setTip(null),
    }),
    [],
  )
  return (
    <TipContext.Provider value={bind}>
      {children}
      {tip ? <TipBox tip={tip} /> : null}
    </TipContext.Provider>
  )
}

function TipBox({ tip }: { tip: TipState }) {
  const ref = useRef<HTMLDivElement>(null)
  // Keep the box inside the window, whatever its size turns out to be.
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    el.style.left = `${Math.max(8, Math.min(tip.x + 14, window.innerWidth - r.width - 8))}px`
    el.style.top = `${Math.max(8, Math.min(tip.y + 14, window.innerHeight - r.height - 8))}px`
  })
  return (
    <div ref={ref} role="tooltip" className="pointer-events-none fixed z-50 max-w-[340px] rounded-lg border border-line-2 bg-tip px-3 py-2.5 text-xs shadow-[0_16px_40px_rgb(0_0_0/0.6)]">
      <b className="mb-1 block font-semibold text-strong">{tip.title}</b>
      {tip.lines.map((line, i) => (
        <div key={i} className="num">{line}</div>
      ))}
    </div>
  )
}
