/** Seconds as minutes:seconds, for a game time. */
export const clock = (s: number | null | undefined): string =>
  s == null ? '–' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

export const rate = (wins: number, losses: number): string =>
  wins + losses ? `${Math.round((100 * wins) / (wins + losses))}%` : '–'

export const record = (wins: number, losses: number): string => `${wins}–${losses}`

export const plural = (n: number, word: string, many?: string): string => `${n} ${n === 1 ? word : (many ?? `${word}s`)}`

export const num = (v: number | null | undefined): string => (v == null ? '–' : v.toLocaleString('en-US'))
