import type { DashboardTheme, ThemeTypography, ThemeLayout } from "./types";

/**
 * Built-in dashboard themes.
 *
 * Each theme defines its own palette, typography, and layout so switching
 * themes produces visible changes beyond just color — fonts, density, and
 * corner-radius all shift to match the theme's personality.
 *
 * Theme names must stay in sync with the backend's
 * `_BUILTIN_DASHBOARD_THEMES` list in `zeus_cli/web_server.py`.
 */

// ---------------------------------------------------------------------------
// Shared typography / layout presets
// ---------------------------------------------------------------------------

/** Default system stack — neutral, safe fallback for every platform. */
const SYSTEM_SANS =
  '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif';
const SYSTEM_MONO =
  '"JetBrains Mono", "Cascadia Code", Consolas, monospace';

const DEFAULT_TYPOGRAPHY: ThemeTypography = {
  fontSans: SYSTEM_SANS,
  fontMono: SYSTEM_MONO,
  fontDisplay: `Bahnschrift, ${SYSTEM_SANS}`,
  baseSize: "15px",
  lineHeight: "1.5",
  letterSpacing: "0",
};

const DEFAULT_LAYOUT: ThemeLayout = {
  radius: "0.75rem",
  density: "comfortable",
};

// ---------------------------------------------------------------------------
// Themes
// ---------------------------------------------------------------------------

export const defaultTheme: DashboardTheme = {
  name: "default",
  label: "Zeus · Storm",
  description: "Storm blue workspace with copper details and a bright paper canvas",
  palette: {
    background: { hex: "#EAF0F7", alpha: 1 },
    midground: { hex: "#162743", alpha: 1 },
    foreground: { hex: "#FFFFFF", alpha: 1 },
    warmGlow: "rgba(168, 95, 50, 0.12)",
    noiseOpacity: 0,
  },
  typography: DEFAULT_TYPOGRAPHY,
  layout: DEFAULT_LAYOUT,
  terminalBackground: "#101D31",
  terminalForeground: "#E5EDF7",
  colorOverrides: {
    card: "#FFFFFF", cardForeground: "#162743",
    popover: "#FFFFFF", popoverForeground: "#162743",
    primary: "#315B83", primaryForeground: "#FFFFFF",
    secondary: "#F7FAFD", secondaryForeground: "#162743",
    muted: "#DFE8F2", mutedForeground: "#51647D",
    accent: "#F7EDE5", accentForeground: "#A85F32",
    border: "#C5D3E2", input: "#B6C7D9", ring: "#315B83",
    destructive: "#B73746", success: "#24725D", warning: "#906413",
  },
  componentStyles: { sidebar: { background: "#F7FAFD" } },
  seriesColors: { inputTokenAccent: "#315B83", outputTokenAccent: "#A85F32" },
  swatchColors: ["#EAF0F7", "#315B83", "#A85F32"],
};

export const midnightTheme: DashboardTheme = {
  name: "midnight",
  label: "Zeus · Night",
  description: "Deep storm blue with warm copper controls",
  palette: {
    background: { hex: "#101D31", alpha: 1 },
    midground: { hex: "#E5EDF7", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(230, 171, 128, 0.12)",
    noiseOpacity: 0,
  },
  typography: DEFAULT_TYPOGRAPHY,
  layout: DEFAULT_LAYOUT,
  terminalBackground: "#101D31",
  terminalForeground: "#E5EDF7",
  colorOverrides: {
    card: "#172842", cardForeground: "#E5EDF7",
    popover: "#172842", popoverForeground: "#E5EDF7",
    primary: "#92B9DD", primaryForeground: "#101D31",
    secondary: "#203650", secondaryForeground: "#E5EDF7",
    muted: "#203650", mutedForeground: "#B0C3D8",
    accent: "#3A302D", accentForeground: "#E6AB80",
    border: "#354C66", input: "#496481", ring: "#92B9DD",
    destructive: "#F18F9D", destructiveForeground: "#101D31", success: "#87C7AE", warning: "#DDBB76",
  },
  componentStyles: { sidebar: { background: "#172842" } },
  seriesColors: { inputTokenAccent: "#92B9DD", outputTokenAccent: "#E6AB80" },
  swatchColors: ["#101D31", "#92B9DD", "#E6AB80"],
};

export const emberTheme: DashboardTheme = {
  name: "ember",
  label: "Ember",
  description: "Warm crimson and bronze — forge vibes",
  palette: {
    background: { hex: "#1a0a06", alpha: 1 },
    midground: { hex: "#ffd8b0", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(249, 115, 22, 0.38)",
    noiseOpacity: 1,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"Spectral", Georgia, "Times New Roman", serif`,
    fontMono: `"IBM Plex Mono", ${SYSTEM_MONO}`,
    fontUrl:
      "https://fonts.googleapis.com/css2?family=Spectral:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;700&display=swap",
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "0.25rem",
  },
  colorOverrides: {
    destructive: "#c92d0f",
    warning: "#f97316",
  },
};

export const monoTheme: DashboardTheme = {
  name: "mono",
  label: "Mono",
  description: "Clean grayscale — minimal and focused",
  palette: {
    background: { hex: "#0e0e0e", alpha: 1 },
    midground: { hex: "#eaeaea", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(255, 255, 255, 0.1)",
    noiseOpacity: 0.6,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"IBM Plex Sans", ${SYSTEM_SANS}`,
    fontMono: `"IBM Plex Mono", ${SYSTEM_MONO}`,
    fontUrl:
      "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap",
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "0",
  },
};

export const cyberpunkTheme: DashboardTheme = {
  name: "cyberpunk",
  label: "Cyberpunk",
  description: "Neon green on black — matrix terminal",
  palette: {
    background: { hex: "#040608", alpha: 1 },
    midground: { hex: "#9bffcf", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(0, 255, 136, 0.22)",
    noiseOpacity: 1.2,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"Share Tech Mono", "JetBrains Mono", ${SYSTEM_MONO}`,
    fontMono: `"Share Tech Mono", "JetBrains Mono", ${SYSTEM_MONO}`,
    fontUrl:
      "https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=JetBrains+Mono:wght@400;700&display=swap",
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "0",
  },
  colorOverrides: {
    success: "#00ff88",
    warning: "#ffd700",
    destructive: "#ff0055",
  },
};

export const roseTheme: DashboardTheme = {
  name: "rose",
  label: "Rosé",
  description: "Soft pink and warm ivory — easy on the eyes",
  palette: {
    background: { hex: "#1a0f15", alpha: 1 },
    midground: { hex: "#ffd4e1", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(249, 168, 212, 0.3)",
    noiseOpacity: 0.9,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"Fraunces", Georgia, serif`,
    fontMono: `"DM Mono", ${SYSTEM_MONO}`,
    fontUrl:
      "https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=DM+Mono:wght@400;500&display=swap",
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "1rem",
  },
};

/** Stable persisted id retained for older installations. */
export const nousBlueTheme: DashboardTheme = {
  ...defaultTheme,
  name: "nous-blue",
  label: "Zeus · Paper",
  description: "The Zeus storm palette with a light terminal",
  terminalBackground: "#F7FAFD",
  terminalForeground: "#162743",
};

/**
 * Same look as ``defaultTheme`` but with a larger root font size, looser
 * line-height, and ``spacious`` density so every rem-based size in the
 * dashboard scales up. For users who find the default 15px UI too dense.
 */
export const defaultLargeTheme: DashboardTheme = {
  ...defaultTheme,
  name: "default-large",
  label: "Zeus · Large",
  description: "ZeusAgent with bigger fonts and roomier spacing",
  palette: defaultTheme.palette,
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    baseSize: "18px",
    lineHeight: "1.65",
  },
  layout: {
    ...DEFAULT_LAYOUT,
    density: "spacious",
  },
};

export const BUILTIN_THEMES: Record<string, DashboardTheme> = {
  default: defaultTheme,
  "default-large": defaultLargeTheme,
  "nous-blue": nousBlueTheme,
  midnight: midnightTheme,
  ember: emberTheme,
  mono: monoTheme,
  cyberpunk: cyberpunkTheme,
  rose: roseTheme,
};
