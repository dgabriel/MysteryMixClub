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

        // --- Light surface: public pages only (ADR 0013) --------------------
        // Design System v1.0 derives its entire foreground ramp against
        // near-black, so on a light page every one of those tokens fails AA:
        // `foreground` measures 1.09:1 on white, `muted-foreground` 3.23:1,
        // `accent` 2.62:1, `link` 2.42:1, `destructive-text` 2.86:1. A light
        // surface therefore needs its own ramp — this is not a surface swap.
        //
        // Every value below KEEPS ITS DARK-SURFACE HUE and is the maximum
        // chroma that still clears its WCAG floor on `paper` while staying
        // inside the sRGB gamut, so the two ramps read as one system seen at
        // two lightnesses rather than two palettes. Solved numerically, not by
        // eye; re-run that solve if `paper` ever stops being pure white.
        //
        // RATIOS ARE COMPUTED FROM THE ROUNDED 8-BIT sRGB VALUE, not from the
        // pre-rounding float. That is not pedantry: the first cut of this ramp
        // was solved on floats and shipped `ink-muted` at a theoretical 4.50:1
        // which the browser actually painted as #76777B — 4.47:1, an AA
        // failure caught only by measuring the live page. Quantization can cost
        // ~0.05, so each value here carries margin over its floor.
        //
        // These are for the five public routes (/login, /about, /terms,
        // /privacy, /help). Cards, TopNav and every authed screen stay dark
        // and keep the tokens above. Do not mix the two ramps on one surface.
        paper: "oklch(1 0 0 / <alpha-value>)", // #FFFFFF light page background
        ink: "oklch(0.34 0.02 80 / <alpha-value>)", // #3D372C 11.79:1 primary text
        "ink-muted": "oklch(0.56 0.006 270 / <alpha-value>)", // #737478 4.67:1 supporting
        "ink-accent": "oklch(0.574 0.142 55 / <alpha-value>)", // #B65D00 4.61:1 amber on paper
        // The hero wordmark only. WCAG's floor for large text (>=18.66px bold /
        // >=24px) is 3:1, not 4.5:1, which buys back most of the chroma the
        // AA-safe `ink-accent` has to spend. NEVER use this at body size.
        "ink-accent-display": "oklch(0.675 0.167 55 / <alpha-value>)", // #E27501 3.10:1
        "ink-link": "oklch(0.56 0.119 235 / <alpha-value>)", // #007EB0 4.55:1 navigation
        "ink-destructive": "oklch(0.595 0.241 25 / <alpha-value>)", // #EC0128 4.56:1 error text
        // Light-surface counterpart to `hairline`. Same fixed-alpha rule: the
        // alpha is the token's whole meaning, so no opacity modifier.
        "ink-hairline": "rgba(0, 0, 0, 0.12)", // rule / divider on paper

        // Light-surface counterpart to `accent-surface` — the tinted callout
        // block. Solved the same way as the ramp above, and it comes with a
        // trap worth stating outright:
        //
        // THE INK RAMP IS SOLVED AGAINST PURE WHITE, SO ANY TINT ERODES IT.
        // On this fill `ink-accent` measures 4.32:1 and `ink-muted` 4.38:1 —
        // both AA failures, despite clearing 4.5 on `paper` itself. Only `ink`
        // survives unchanged (11.05:1). So: body copy on this surface is `ink`,
        // never `ink-muted`, and amber on it is `ink-accent-deep` below, never
        // `ink-accent`.
        "ink-accent-surface": "oklch(0.98 0.015 55 / <alpha-value>)", // #FFF6EF callout fill
        // `ink-accent` re-solved for `ink-accent-surface` instead of `paper`:
        // same hue (55) and same chroma (0.142), dropped in lightness until it
        // clears the floor with margin. 4.76:1 on the tint, 5.08:1 on paper, so
        // it is safe on both and the two never need swapping mid-component.
        "ink-accent-deep": "oklch(0.55 0.142 55 / <alpha-value>)", // #AE5600 amber on the tint

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
        // Light-surface counterparts (ADR 0013). The dark ladder's shadows are
        // black at 0.65-0.95 alpha with a white inner ring — on paper they read
        // as bruises rather than depth, and the white ring disappears entirely.
        // These drop to 0.08-0.18 alpha and swap the ring to black, because on a
        // light surface it is the ring, not the blur, that defines the edge.
        "z2-ink": "0 4px 14px rgba(0,0,0,0.10), 0 1px 0 rgba(0,0,0,0.04)",
        "art-ink":
          "0 18px 44px rgba(0,0,0,0.18), 0 4px 10px rgba(0,0,0,0.10), 0 0 0 1px rgba(0,0,0,0.08)",
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
