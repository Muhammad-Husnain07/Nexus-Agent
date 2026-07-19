import { useEffect } from "react";

type KeyMap = Record<string, () => void>;

export function useKeyPress(keyMap: KeyMap) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const key = e.key === " " ? "Space" : e.key;
      const ctrl = e.ctrlKey || e.metaKey ? "Cmd+" : "";
      const shift = e.shiftKey ? "Shift+" : "";
      const combo = `${ctrl}${shift}${key}`;
      if (keyMap[combo]) {
        e.preventDefault();
        keyMap[combo]();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [keyMap]);
}
