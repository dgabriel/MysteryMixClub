/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        cream: "#F0EDE6",
        ink: "#2E2B27",
        sage: "#7A9E82",
        "sage-light": "#A8C4AD",
        "sage-pale": "#D4E3D7",
        rust: "#B5533C",
        muted: "#8A8680",
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
