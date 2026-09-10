import { describe, expect, it } from 'vitest'

import { contrastRatio } from './color'
import {
  BUILTIN_THEME_LIST,
  BUILTIN_THEMES,
  DEFAULT_SKIN_NAME,
  DEFAULT_TYPOGRAPHY,
  EMOJI_FALLBACK,
  LEGACY_SKIN_NAMES,
  zeusTheme
} from './presets'
import { resolveTheme } from './user-themes'

// #40364: none of the UI text/mono fonts carry emoji glyphs, so every font
// stack must end with a color-emoji fallback or emoji render as tofu on
// platforms whose default font lacks them (e.g. Linux).
describe('theme typography emoji fallback (#40364)', () => {
  const stacks: Array<[string, string]> = [
    ['DEFAULT_TYPOGRAPHY.fontSans', DEFAULT_TYPOGRAPHY.fontSans],
    ['DEFAULT_TYPOGRAPHY.fontMono', DEFAULT_TYPOGRAPHY.fontMono],
    // A theme may override only fontMono (fontSans then falls back to the
    // default, which already carries the emoji stack), so skip undefined.
    ...BUILTIN_THEME_LIST.flatMap(theme =>
      (
        [
          [`${theme.name}.fontSans`, theme.typography?.fontSans],
          [`${theme.name}.fontMono`, theme.typography?.fontMono]
        ] as Array<[string, string | undefined]>
      ).filter((entry): entry is [string, string] => typeof entry[1] === 'string')
    )
  ]

  it.each(stacks)('%s includes a color-emoji font', (_label, stack) => {
    expect(stack).toMatch(/Apple Color Emoji|Segoe UI Emoji|Noto Color Emoji|(^|,\s*)emoji\b/)
  })

  it('EMOJI_FALLBACK lists the major platform emoji fonts', () => {
    expect(EMOJI_FALLBACK).toContain('Apple Color Emoji')
    expect(EMOJI_FALLBACK).toContain('Segoe UI Emoji')
    expect(EMOJI_FALLBACK).toContain('Noto Color Emoji')
  })
})

describe('Zeus identity and previous installation compatibility', () => {
  it('offers Zeus as the default without exposing retired brand choices', () => {
    expect(BUILTIN_THEMES[DEFAULT_SKIN_NAME]).toBe(zeusTheme)
    expect(BUILTIN_THEME_LIST.some(theme => theme.name in LEGACY_SKIN_NAMES)).toBe(false)
  })

  it.each(Object.keys(LEGACY_SKIN_NAMES))('resolves the saved %s name to the new identity', name => {
    expect(resolveTheme(name)).toBe(zeusTheme)
  })

  it.each([zeusTheme.colors, zeusTheme.darkColors!])('keeps actions, text and focus readable in both modes', colors => {
    expect(contrastRatio(colors.primary, colors.primaryForeground)).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(colors.foreground, colors.background)).toBeGreaterThanOrEqual(7)
    expect(contrastRatio(colors.mutedForeground, colors.card)).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(colors.ring, colors.card)).toBeGreaterThanOrEqual(3)
    expect(colors.primary).not.toBe(colors.ring)
  })

  it('does not require a network font request for the default identity', () => {
    expect(zeusTheme.typography?.fontUrl).toBeUndefined()
  })
})
