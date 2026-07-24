import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ThemeState {
  theme: "light" | "dark";
  toggleTheme: () => void;
  setTheme: (t: "light" | "dark") => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: "dark",
      toggleTheme: () => set((s) => ({ theme: s.theme === "dark" ? "light" : "dark" })),
      setTheme: (theme) => set({ theme }),
    }),
    { name: "nexus-theme" }
  )
);

interface ChatState {
  activeSessionId: string | null;
  setActiveSession: (id: string | null) => void;
  streaming: boolean;
  setStreaming: (v: boolean) => void;
}

export const useChatStore = create<ChatState>()((set) => ({
  activeSessionId: null,
  setActiveSession: (id) => set({ activeSessionId: id }),
  streaming: false,
  setStreaming: (v) => set({ streaming: v }),
}));

interface SidebarState {
  collapsed: boolean;
  toggle: () => void;
}

export const useSidebarStore = create<SidebarState>()((set) => ({
  collapsed: false,
  toggle: () => set((s) => ({ collapsed: !s.collapsed })),
}));
