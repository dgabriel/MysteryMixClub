/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Design System v1.0 (ADR 0009). Colors are shipped as the `oklch()`
      // strings the approved style tile actually renders, each carrying the
      // `<alpha-value>` placeholder so opacity modifiers (`bg-card/50`) still
      // work — Tailwind v3 passes arbitrary color strings through untouched.
      // Hex comments are documentation for contrast math only; the two places
      // that need a literal hex (index.html theme-color, manifest.json) carry
      // it directly because neither file can read a token.
      colors: {
        // --- Surface ladder (Z0 -> Z4) -------------------------------------
        floor: "oklch(0.10 0.004 270 / <alpha-value>)", // #030304 Z0 page background
        sunken: "oklch(0.13 0.003 270 / <alpha-value>)", // #070708 chrome below content
        card: "oklch(0.16 0.003 270 / <alpha-value>)", // #0D0D0F Z1 content surface
        popover: "oklch(0.20 0.003 270 / <alpha-value>)", // #151617 transient surfaces
        tile: "oklch(0.22 0.003 270 / <alpha-value>)", // #1A1B1C Z2 interactive tile
        panel: "oklch(0.28 0.003 270 / <alpha-value>)", // #28292A Z3 elevated panel
        sheet: "oklch(0.35 0.003 270 / <alpha-value>)", // #3A3A3C Z4 modal / drawer
        "accent-surface": "oklch(0.20 0.01 55 / <alpha-value>)", // #1A1512 achievement row
        track: "oklch(0.35 0.006 270 / <alpha-value>)", // #393A3E unfilled bar

        // --- Foreground ramp ------------------------------------------------
        foreground: "oklch(0.97 0.006 80 / <alpha-value>)", // #F7F5F1 primary text
        "muted-foreground": "oklch(0.65 0.006 270 / <alpha-value>)", // #8E8F93 supporting text
        "subtle-foreground": "oklch(0.60 0.006 270 / <alpha-value>)", // #7F8084 Z0/Z1 only
        "faint-foreground": "oklch(0.55 0.004 270 / <alpha-value>)", // #707174 annotation only
        "ghost-foreground": "oklch(0.48 0.003 270 / <alpha-value>)", // #5D5D5F never text

        // --- Accent (amber) -------------------------------------------------
        accent: "oklch(0.72 0.17 55 / <alpha-value>)", // #F3821D action or achievement
        // Hover step for an `accent` fill. Brightens rather than dims, so the
        // control gains presence on hover the way the retired sage -> sage-light
        // pair did. `accent-foreground` on it is 10.36:1.
        // Verified in sRGB gamut (max linear channel 0.9805) and round-trips to
        // oklch(0.790 0.140 57.8). An out-of-gamut value would be a bug, not a
        // rounding artifact: gamut mapping is implementation-dependent below
        // one JND, so the rendered color would stop being knowable.
        "accent-hover": "oklch(0.79 0.14 58 / <alpha-value>)", // #FDA258
        "accent-foreground": "oklch(0.08 0 0 / <alpha-value>)", // #020202 text on amber
        "accent-hairline": "rgba(201, 139, 48, 0.25)", // amber-tinted 1px rule

        // --- Link -----------------------------------------------------------
        // Navigation, not action. Amber was carrying links as well as actions,
        // achievements, the brand mark and the active nav item; giving links
        // their own hue is what lets the amber ones read.
        //
        // Not an arbitrary blue: `accent` is hue 55, so its exact OKLCH
        // complement is hue 235 — the opposite side of the same wheel. Lightness
        // matches `accent` (0.72) so the two read as siblings in one system
        // rather than a blue borrowed from elsewhere. Chroma is 0.13 against
        // amber's 0.17 on purpose: blue at high chroma glares on near-black, and
        // a link should not shout louder than a button.
        //
        // 8.03:1 on `card`, 8.53:1 on `floor`. Verified in sRGB gamut and
        // round-trips to oklch(0.720 0.130 235.0). Links are always underlined,
        // so the affordance never rests on hue alone.
        link: "oklch(0.72 0.13 235 / <alpha-value>)", // #3FB1EA navigation

        // --- Status ---------------------------------------------------------
        destructive: "oklch(0.55 0.22 25 / <alpha-value>)", // #D40924 fill only, never text
        // Hover step for a `destructive` fill. This one DEEPENS where
        // `accent-hover` brightens: `destructive-foreground` on `destructive`
        // has only 0.49 of headroom over 4.5:1, and a brighter red spends it
        // (L 0.58 -> #DF202E -> 4.39:1, an AA failure). Deepening buys headroom
        // instead (5.58:1) and still clears 3:1 against `card` (3.19:1) and
        // `floor` (3.39:1). L 0.52 is about as deep as it can go and keep that
        // boundary ratio.
        // Verified in sRGB gamut (min linear channel 0.0161) and round-trips to
        // oklch(0.520 0.190 24.9).
        "destructive-hover": "oklch(0.52 0.19 25 / <alpha-value>)", // #BE222A
        "destructive-foreground": "oklch(0.97 0 0 / <alpha-value>)", // #F5F5F5 text on fill
        "destructive-text": "oklch(0.70 0.16 25 / <alpha-value>)", // #F2716A error text (ADR 0004)
        positive: "oklch(0.65 0.12 145 / <alpha-value>)", // #5DA260 upward delta
        negative: "oklch(0.62 0.18 25 / <alpha-value>)", // #DE4E4B downward delta

        // --- Hairlines ------------------------------------------------------
        // These four (and `accent-hairline` above) deliberately ship as
        // fixed-alpha rgba() WITHOUT the `<alpha-value>` placeholder: the alpha
        // is the token's entire meaning, there are exactly three sanctioned
        // steps, and allowing `border-hairline/50` would reintroduce the
        // arbitrary-alpha freedom this ladder exists to remove. Opacity
        // modifiers on these are silently ignored — pick the right step.
        "hairline-soft": "rgba(255, 255, 255, 0.05)", // dividers within a card
        hairline: "rgba(255, 255, 255, 0.09)", // default card / section edge
        "hairline-strong": "rgba(255, 255, 255, 0.12)", // floating element over artwork

        // --- Chart series (ADR 0008) ----------------------------------------
        "chart-1": "oklch(0.72 0.17 55 / <alpha-value>)", // #F3821D (identical to accent)
        "chart-2": "oklch(0.65 0.12 180 / <alpha-value>)", // #00A692 teal
        "chart-3": "oklch(0.60 0.14 240 / <alpha-value>)", // #0089CA blue
        "chart-4": "oklch(0.62 0.18 25 / <alpha-value>)", // #DE4E4B red
        "chart-5": "oklch(0.78 0.08 80 / <alpha-value>)", // #D2B27C sand

      },
      // Elevation. The shadow index does NOT track the surface index — a Z1
      // card wears shadow-z2 at rest. See docs/design/style-guide.md.
      boxShadow: {
        z0: "none",
        z1: "0 1px 4px rgba(0,0,0,0.65)",
        z2: "0 4px 14px rgba(0,0,0,0.72), 0 1px 0 rgba(255,255,255,0.04)",
        z3: "0 8px 26px rgba(0,0,0,0.80), 0 2px 0 rgba(255,255,255,0.05)",
        z4: "0 18px 52px rgba(0,0,0,0.88), 0 4px 8px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.08)",
        art: "0 24px 72px rgba(0,0,0,0.95), 0 8px 24px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.10)",
      },
      fontFamily: {
        display: ['"Big Shoulders Display"', "sans-serif"],
        sans: ['"Libre Franklin"', "system-ui", "-apple-system", "sans-serif"],
        // Alias of `sans`, for components where `font-body` reads better next
        // to `font-display` than `font-sans` would.
        body: ['"Libre Franklin"', "system-ui", "-apple-system", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      // Sub-`text-xs` steps the DS needs. `text-micro` is non-information-
      // bearing chrome only; the floor for any label a user must read is
      // `text-mini`.
      fontSize: {
        micro: ["0.55rem", { lineHeight: "1.4" }],
        mini: ["0.6rem", { lineHeight: "1.4" }],
        label: ["0.65rem", { lineHeight: "1.4" }],
        meta: ["0.7rem", { lineHeight: "1.5" }],
      },
      borderRadius: {
        hair: "1px", // inner elements: art, badges, chips, bars, buttons
        tile: "2px", // containers: cards, sections, panels (= DS --radius)
      },
      letterSpacing: {
        "display-hero": "-0.025em",
        "display-tight": "-0.02em",
        "display-snug": "-0.01em",
        "mono-sm": "0.04em",
        mono: "0.06em",
        "mono-caps": "0.08em",
        "mono-wide": "0.10em",
        "mono-widest": "0.12em",
      },
      keyframes: {
        "rotate-rings": {
          from: { transform: "rotate(0deg)" },
          to: { transform: "rotate(360deg)" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
      },
      animation: {
        // 6s matches the style tile's VinylDisc rotation. The animation and
        // keyframe NAMES are load-bearing — AdminMetricsRoute.test.tsx queries
        // `.animate-rotate-rings` in five places — but those assert the class,
        // never the duration, so retuning is safe where renaming would not be.
        "rotate-rings": "rotate-rings 6s linear infinite",
        // Subtle page/section fade per the style guide — no staged motion.
        "fade-in": "fade-in 200ms ease",
      },
    },
  },
  plugins: [],
};
