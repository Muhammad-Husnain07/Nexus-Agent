import { create } from "zustand"
import { persist } from "zustand/middleware"

type ThemeMode = "light" | "dark"

interface ThemeStore {
  mode: ThemeMode
  toggleTheme: () => void
  setMode: (mode: ThemeMode) => void
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set, get) => ({
      mode: "light",

      toggleTheme: () => {
        const next = get().mode === "light" ? "dark" : "light"
        set({ mode: next })
        applyTheme(next)
      },

      setMode: (mode) => {
        set({ mode })
        applyTheme(mode)
      },
    }),
    { name: "nexus-theme" },
  ),
)

function applyTheme(mode: ThemeMode) {
  document.documentElement.classList.toggle("dark", mode === "dark")
}

// Apply on load
const stored = localStorage.getItem("nexus-theme")
if (stored) {
  try {
    const parsed = JSON.parse(stored)
    if (parsed?.state?.mode) {
      applyTheme(parsed.state.mode)
    }
  } catch {
    // ignore
  }
}
