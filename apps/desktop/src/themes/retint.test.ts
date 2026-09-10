import { describe, expect, it } from 'vitest'

import { contrastRatio, hexToOklch, withHue } from './color'
import { githubTheme } from './presets'
import { retintTheme, themeHue } from './retint'
import type { DesktopTheme, DesktopThemeColors } from './types'

const testTheme: DesktopTheme = {
  name: 'test-blue',
  label: 'Test blue',
  description: 'A paired blue fixture for hue and contrast regression tests',
  colors: {
    background: '#ffffff',
    foreground: '#1f2328',
    card: '#f6f8fa',
    cardForeground: '#1f2328',
    muted: '#f6f6f6',
    mutedForeground: '#656d76',
    popover: '#ffffff',
    popoverForeground: '#1f2328',
    primary: '#0053fd',
    primaryForeground: '#ffffff',
    secondary: '#deeaff',
    secondaryForeground: '#1f2328',
    accent: '#e3edff',
    accentForeground: '#1f2328',
    border: '#d0d7de',
    input: '#ffffff',
    ring: '#0053fd',
    midground: '#0053fd',
    midgroundForeground: '#ffffff',
    composerRing: '#0053fd',
    destructive: '#cf222e',
    destructiveForeground: '#ffffff',
    sidebarBackground: '#f6f8fa',
    sidebarBorder: '#d0d7de',
    userBubble: '#dae7fd',
    userBubbleBorder: '#d0d7de'
  },
  darkColors: {
    background: '#0d1117',
    foreground: '#e6edf3',
    card: '#010409',
    cardForeground: '#e6edf3',
    muted: '#1a1e24',
    mutedForeground: '#7d8590',
    popover: '#161b22',
    popoverForeground: '#e6edf3',
    primary: '#4a84fe',
    primaryForeground: '#161616',
    secondary: '#1d2e4f',
    secondaryForeground: '#e6edf3',
    accent: '#17243a',
    accentForeground: '#e6edf3',
    border: '#30363d',
    input: '#0d1117',
    ring: '#4a84fe',
    midground: '#4a84fe',
    midgroundForeground: '#161616',
    composerRing: '#4a84fe',
    destructive: '#f85149',
    destructiveForeground: '#ffffff',
    sidebarBackground: '#010409',
    sidebarBorder: '#30363d',
    userBubble: '#07162c',
    userBubbleBorder: '#30363d'
  }
}

const HUES = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330]

// A retint seed for each hue, at the authored accent's lightness/chroma.
const seedAt = (hue: number) => withHue(testTheme.colors.primary, hue)

const TEST_BLUE = '#0053FD'

describe('themeHue', () => {
  it('reads the accent hue that ships', () => {
    // The fixture blue. Both palettes sit at this hue — light seeds `#0053fd` and dark
    // `#4a84fe`, the same blue at two lightnesses, which is what lets one pick
    // serve both appearances.
    expect(themeHue(testTheme)).toBe(263)
    expect(Math.round(hexToOklch(testTheme.darkColors!.primary)!.h)).toBe(263)
  })

  it('reads the upstream GitHub green from the unforked theme', () => {
    // `github` keeps the original accent, so the fork's blue can move freely
    // without redefining what upstream looks like.
    expect(themeHue(githubTheme)).toBe(148)
    expect(Math.round(hexToOklch(githubTheme.darkColors!.primary)!.h)).toBe(148)
  })
})

// The two seeds are the whole point of the fork, and both are load-bearing:
// `#0053FD` is the brand color and passes on the light sidebar, but only 3.6:1
// on the near-black dark one — so dark carries a lifted twin rather than the
// literal brand hex. Anything that re-derives these must keep both legible.
describe('the paired fixture accents', () => {
  const cases = [
    { appearance: 'light', colors: testTheme.colors, seed: '#0053fd' },
    { appearance: 'dark', colors: testTheme.darkColors!, seed: '#4a84fe' }
  ] as const

  it.each(cases)('$appearance seeds every accent slot from $seed', ({ colors, seed }) => {
    for (const key of ['primary', 'ring', 'midground', 'composerRing'] as const) {
      expect(colors[key]).toBe(seed)
    }
  })

  it.each(cases)('$appearance clears AA on its own sidebar', ({ colors, seed }) => {
    expect(contrastRatio(seed, colors.sidebarBackground!)).toBeGreaterThanOrEqual(4.5)
  })

  it.each(cases)('$appearance keeps text on the accent readable', ({ colors, seed }) => {
    expect(contrastRatio(seed, colors.primaryForeground)).toBeGreaterThanOrEqual(4.5)
  })

  it('is one blue at two lightnesses, not two blues', () => {
    const light = hexToOklch(testTheme.colors.primary)!
    const dark = hexToOklch(testTheme.darkColors!.primary)!

    expect(Math.abs(light.h - dark.h)).toBeLessThan(2)
    expect(dark.l).toBeGreaterThan(light.l)
  })

  it('leaves GitHub’s neutrals in place — only the accent family is forked', () => {
    for (const key of ['background', 'foreground', 'card', 'border', 'sidebarBackground'] as const) {
      expect(testTheme.colors[key]).toBe(githubTheme.colors[key])
      expect(testTheme.darkColors![key]).toBe(githubTheme.darkColors![key])
    }
  })
})

describe('retintTheme', () => {
  // The load-bearing property: the mix ratios in retint.ts must be the same
  // ones that produced the shipped palette. If they drift, retinting at the
  // theme's OWN hue stops being a no-op — and this catches it.
  it('is an identity at the theme’s own accent', () => {
    const same = retintTheme(testTheme, testTheme.colors.primary)

    expect(same.colors).toEqual(testTheme.colors)
    expect(same.darkColors).toEqual(testTheme.darkColors)
  })

  it('moves every accent-family slot, in both modes', () => {
    const rose = retintTheme(testTheme, seedAt(350))

    for (const mode of ['colors', 'darkColors'] as const) {
      const before = testTheme[mode]!
      const after = rose[mode]!

      for (const key of [
        'primary',
        'ring',
        'midground',
        'composerRing',
        'accent',
        'secondary',
        'userBubble'
      ] as const) {
        expect(after[key], `${mode}.${key}`).not.toBe(before[key])
      }
    }
  })

  it('keeps the four seed slots locked together', () => {
    const teal = retintTheme(testTheme, seedAt(195)).colors

    expect(teal.ring).toBe(teal.primary)
    expect(teal.midground).toBe(teal.primary)
    expect(teal.composerRing).toBe(teal.primary)
  })

  it('leaves the chrome alone', () => {
    // The neutrals are the app's surface, not its brand. A hue knob that also
    // swung these would make every theme a monochrome wash.
    const violet = retintTheme(testTheme, seedAt(285))

    for (const key of ['background', 'foreground', 'card', 'border', 'muted', 'mutedForeground'] as const) {
      expect(violet.colors[key], key).toBe(testTheme.colors[key])
      expect(violet.darkColors![key], `dark ${key}`).toBe(testTheme.darkColors![key])
    }
  })

  it('holds perceived lightness and chroma while only the hue moves', () => {
    const base = hexToOklch(testTheme.colors.primary)!

    for (const hue of HUES) {
      const seed = hexToOklch(retintTheme(testTheme, seedAt(hue)).colors.primary)!

      expect(Math.abs(seed.l - base.l), `L at ${hue}`).toBeLessThan(0.02)
      // Chroma can only be REDUCED, and only where sRGB can't show it.
      expect(seed.c, `C at ${hue}`).toBeLessThanOrEqual(base.c + 0.005)
    }
  })

  // The accent labels the sidebar in small uppercase text, so a hue that
  // collapses against it ships invisible section headers.
  it('keeps the accent readable on the sidebar at every hue', () => {
    for (const hue of HUES) {
      const t = retintTheme(testTheme, seedAt(hue))

      for (const mode of ['colors', 'darkColors'] as const) {
        const c = t[mode] as DesktopThemeColors
        const ratio = contrastRatio(c.primary, c.sidebarBackground ?? c.background)

        expect(ratio, `${mode} @ ${hue}°`).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it('re-picks the foreground that sits on the accent', () => {
    for (const hue of HUES) {
      const c = retintTheme(testTheme, seedAt(hue)).colors

      expect(contrastRatio(c.primary, c.primaryForeground), `on-accent @ ${hue}°`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('accepts any hex form and ignores junk', () => {
    expect(retintTheme(testTheme, '#0053FD').colors.primary).toBe(retintTheme(testTheme, '0053fd').colors.primary)
    // A half-typed hex from a text input must not blow up the theme.
    expect(retintTheme(testTheme, '#00').colors).toEqual(testTheme.colors)
    expect(retintTheme(testTheme, 'nonsense').colors).toEqual(testTheme.colors)
  })

  // The real motivating case: The fixture blue is legible on GitHub's light sidebar
  // (5.4:1) but NOT its dark one (3.6:1), so dark has to adapt or ship
  // invisible section headers.
  describe('a seed that only works in one mode', () => {
    const blue = retintTheme(testTheme, TEST_BLUE)

    it('keeps the picked color where it already passes', () => {
      expect(blue.colors.primary.toLowerCase()).toBe(TEST_BLUE.toLowerCase())
    })

    it('lightens it for the mode where it does not', () => {
      const dark = blue.darkColors!.primary

      expect(dark.toLowerCase()).not.toBe(TEST_BLUE.toLowerCase())
      expect(contrastRatio(dark, blue.darkColors!.sidebarBackground!)).toBeGreaterThanOrEqual(4.5)
    })

    it('adapts by lightness, holding the hue — so it still reads as the brand', () => {
      const picked = hexToOklch(TEST_BLUE)!
      const adapted = hexToOklch(blue.darkColors!.primary)!

      expect(Math.abs(adapted.h - picked.h)).toBeLessThan(3)
      expect(adapted.l).toBeGreaterThan(picked.l)
      // Chroma may only fall because sRGB cannot SHOW that colorfulness at the
      // higher lightness — `#0053FD`'s C 0.26 is out of gamut once lightened,
      // and the clamp trades it away rather than shifting the hue. What must
      // not happen is the mix-toward-white collapse, which would also drag the
      // hue and leave a pastel; staying well clear of half the original chroma
      // is the line between "same blue, lighter" and "washed out".
      expect(adapted.c).toBeGreaterThan(picked.c * 0.55)
    })
  })

  it('does not brand a slot that never tracked the accent', () => {
    // mono's ring is a neutral gray on purpose.
    const neutralRing = {
      ...testTheme,
      colors: { ...testTheme.colors, ring: '#9a9a9a' },
      darkColors: undefined
    }

    expect(retintTheme(neutralRing, '#8250df').colors.ring).toBe('#9a9a9a')
  })

  // A theme may shade its accent across slots rather than repeating one hex —
  // midnight runs a `#8b80e8` ring under a `#ddd6ff` primary. Both are the
  // same violet; matching on exact equality left the ring behind and produced
  // a half-retinted theme.
  describe('a theme whose accent slots are shades of each other', () => {
    const shaded = {
      ...testTheme,
      colors: { ...testTheme.colors, primary: '#ddd6ff', ring: '#8b80e8', midground: '#8b80e8' },
      darkColors: undefined
    }

    it('moves every slot in the family', () => {
      const teal = retintTheme(shaded, '#0f9b8e')

      expect(teal.colors.ring).not.toBe('#8b80e8')
      expect(Math.abs(hexToOklch(teal.colors.ring)!.h - hexToOklch('#0f9b8e')!.h)).toBeLessThan(3)
    })

    it('keeps each slot at its own lightness, rather than flattening them', () => {
      const teal = retintTheme(shaded, '#0f9b8e')
      const ring = hexToOklch(teal.colors.ring)!

      expect(ring.l).toBeCloseTo(hexToOklch('#8b80e8')!.l, 1)
      expect(ring.l).not.toBeCloseTo(hexToOklch(teal.colors.primary)!.l, 1)
    })
  })
})
