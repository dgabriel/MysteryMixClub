/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        cream: "#F0EDE6",
        ink: "#2E2B27",
        sage: "#506755",
        "sage-light": "#A8C4AD",
        "sage-pale": "#D4E3D7",
        rust: "#AD4F39",
        gold: "#83681A",
        vinyl: "#6B7EB5",
        muted: "#6D6A66",
        border: "#D6D2CA",
      },
      fontFamily: {
        serif: ['"DM Serif Display"', "serif"],
        mono: ['"DM Mono"', "monospace"],
      },
      letterSpacing: {
        label: "0.15em",
        ui: "0.12em",
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
        "rotate-rings": "rotate-rings 8s linear infinite",
        // Subtle page/section fade per the style guide — no staged motion.
        "fade-in": "fade-in 200ms ease",
      },
    },
  },
  plugins: [],
};
