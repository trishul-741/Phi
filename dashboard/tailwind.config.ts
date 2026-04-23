import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        night: "#08111d",
        surface: "#0f1a2b",
        line: "rgba(148, 163, 184, 0.18)",
        safe: "#22c55e",
        suspicious: "#f59e0b",
        malicious: "#ef4444",
        accent: "#38bdf8",
      },
      boxShadow: {
        glow: "0 20px 60px rgba(2, 6, 23, 0.35)",
      },
      backgroundImage: {
        "dashboard-glow":
          "radial-gradient(circle at top left, rgba(56, 189, 248, 0.14), transparent 28%), radial-gradient(circle at bottom right, rgba(239, 68, 68, 0.12), transparent 24%)",
      },
    },
  },
  plugins: [],
};

export default config;
