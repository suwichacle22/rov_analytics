// The teams of the league, in the order they are listed, and the look of each one.
//
// The accent is the team colour taken from its logo on the broadcast. To add a team: add an entry
// with its colours. A team without an entry still gets a page, in the default grey.

export interface TeamTheme {
  /** The team colour. Marks the team's wins and the team's own numbers. */
  accent: string
  /** Text colour that is readable on top of the accent. */
  accentInk: string
  /** Page background. */
  bg: string
}

const BG = '#050505'

export const TEAMS: Record<string, { theme: TeamTheme }> = {
  FS: { theme: { accent: '#ff6d1f', accentInk: '#0a0a0a', bg: BG } },
  BRU: { theme: { accent: '#3b5bff', accentInk: '#ffffff', bg: BG } },
  BAC: { theme: { accent: '#ff5fb1', accentInk: '#0a0a0a', bg: BG } },
  KOG: { theme: { accent: '#e4e6ec', accentInk: '#0a0a0a', bg: BG } },
  HD: { theme: { accent: '#4d9cff', accentInk: '#0a0a0a', bg: BG } },
  EA: { theme: { accent: '#ff2d7c', accentInk: '#0a0a0a', bg: BG } },
  TEN: { theme: { accent: '#2fc29c', accentInk: '#0a0a0a', bg: BG } },
  SLX: { theme: { accent: '#f6b921', accentInk: '#0a0a0a', bg: BG } },
  GJC: { theme: { accent: '#5fd68a', accentInk: '#0a0a0a', bg: BG } },
}

export const DEFAULT_TEAM = 'FS'

const DEFAULT_THEME: TeamTheme = { accent: '#d6d6d9', accentInk: '#0a0a0a', bg: BG }

export const themeOf = (teamId: string): TeamTheme => TEAMS[teamId]?.theme ?? DEFAULT_THEME

/** The theme as CSS variables, for the `style` of the page wrapper. */
export function themeVars(teamId: string): Record<string, string> {
  const t = themeOf(teamId)
  return { '--color-accent': t.accent, '--color-accent-ink': t.accentInk, '--color-bg': t.bg }
}
