import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0e0f12",
        paper: "#f7f6f1",
        rule: "#dcd7c7",
        accent: "#a0522d",
        muted: "#5a5750",
      },
      fontFamily: {
        serif: ["ui-serif", "Georgia", "Cambria", "serif"],
        sans: ["ui-sans-serif", "system-ui", "Inter", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
