import { create } from "zustand"
import { persist } from "zustand/middleware"

type ThemeMode = "light" | "dark"

interface ThemeStore {
  mode: ThemeMode
  toggleMode: () => void
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set, get) => ({
      mode: "light",
      toggleMode: () => {
        const next = get().mode === "light" ? "dark" : "light"
        set({ mode: next })
      },
    }),
    { name: "nexus-theme" },
  ),
)
