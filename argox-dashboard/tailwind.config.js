/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--bg-base)",
        surface: {
          DEFAULT: "var(--bg-surface)",
          2: "var(--bg-surface-2)",
          3: "var(--bg-surface-3)",
        },
        overlay: "var(--bg-overlay)",
        border: {
          DEFAULT: "var(--border)",
          soft: "var(--border-soft)",
          strong: "var(--border-strong)",
          faint: "var(--border-faint)",
        },
        text: {
          primary: "var(--text-primary)",
          secondary: "var(--text-secondary)",
          muted: "var(--text-muted)",
          faint: "var(--text-faint)",
          inverse: "var(--text-inverse)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          hover: "var(--accent-hover)",
          press: "var(--accent-press)",
          fg: "var(--accent-fg)",
          surface: "var(--accent-surface)",
          border: "var(--accent-border)",
        },
        peacock: {
          cyan: "var(--peacock-cyan)",
          teal: "var(--peacock-teal)",
          indigo: "var(--peacock-indigo)",
        },
        gold: {
          DEFAULT: "var(--gold)",
          bright: "var(--gold-bright)",
          surface: "var(--gold-surface)",
          border: "var(--gold-border)",
        },
        allow: {
          DEFAULT: "var(--allow)",
          bright: "var(--allow-bright)",
          surface: "var(--allow-surface)",
          border: "var(--allow-border)",
        },
        warn: {
          DEFAULT: "var(--warn)",
          bright: "var(--warn-bright)",
          surface: "var(--warn-surface)",
          border: "var(--warn-border)",
        },
        block: {
          DEFAULT: "var(--block)",
          bright: "var(--block-bright)",
          ink: "var(--block-ink)",
          bg: "var(--block-bg)",
          border: "var(--block-border)",
          edge: "var(--block-edge)",
          glow: "var(--block-glow)",
        },
        span: {
          llm: "var(--span-llm)",
          tool: "var(--span-tool)",
          processor: "var(--span-processor)",
        }
      },
      fontFamily: {
        ui: ["var(--font-ui)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
        display: ["var(--font-display)", "sans-serif"],
      },
      fontSize: {
        "2xs": "var(--fs-2xs)",
        xs: "var(--fs-xs)",
        sm: "var(--fs-sm)",
        base: "var(--fs-base)",
        md: "var(--fs-md)",
        lg: "var(--fs-lg)",
        xl: "var(--fs-xl)",
        "2xl": "var(--fs-2xl)",
        "3xl": "var(--fs-3xl)",
        "4xl": "var(--fs-4xl)",
      },
      borderRadius: {
        xs: "var(--r-xs)",
        sm: "var(--r-sm)",
        md: "var(--r-md)",
        lg: "var(--r-lg)",
        xl: "var(--r-xl)",
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
        pop: "var(--shadow-pop)",
      },
      spacing: {
        "sp-1": "var(--sp-1)",
        "sp-2": "var(--sp-2)",
        "sp-3": "var(--sp-3)",
        "sp-4": "var(--sp-4)",
        "sp-5": "var(--sp-5)",
        "sp-6": "var(--sp-6)",
        "sp-8": "var(--sp-8)",
        "sp-10": "var(--sp-10)",
        "sp-12": "var(--sp-12)",
        "sp-16": "var(--sp-16)",
      }
    },
  },
  plugins: [],
}
