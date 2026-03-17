import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--bg-primary)",
        foreground: "var(--text-primary)",
        paper: "var(--paper)",
        forest: "var(--forest)",
        coral: "var(--coral)",
        grid: "var(--grid)",
        line: "var(--line)",
        // Orange depth palette — use as bg-o-100, text-o-700 etc.
        o: {
          50:  "#fdf6ee",
          100: "#faebd5",
          200: "#f5c89a",
          300: "#eda868",
          400: "#e08840",
          500: "#d06e28",
          600: "#b85618",
          700: "#9a3f10",
          800: "#7a2e0c",
          900: "#4e1c08",
        },
      },
      fontFamily: {
        display: ["Bricolage Grotesque", "sans-serif"],
        body: ["Plus Jakarta Sans", "sans-serif"],
        mono: ["IBM Plex Mono", "monospace"],
      },
      keyframes: {
        fadeInUp: {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        scaleIn: {
          from: { opacity: "0", transform: "scale(0.95)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
        slideDown: {
          from: { opacity: "0", transform: "translateY(-6px) scaleY(0.96)" },
          to: { opacity: "1", transform: "translateY(0) scaleY(1)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
      animation: {
        "fade-in-up": "fadeInUp 0.35s cubic-bezier(0.16, 1, 0.3, 1) both",
        "scale-in": "scaleIn 0.2s cubic-bezier(0.16, 1, 0.3, 1) both",
        "slide-down": "slideDown 0.2s cubic-bezier(0.16, 1, 0.3, 1) both",
        shimmer: "shimmer 2s linear infinite",
      },
      transitionTimingFunction: {
        spring: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
    },
  },
  plugins: [],
};
export default config;
