import { useState, useCallback } from "react";

export function useLocalStorage<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => {
    try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : initialValue; }
    catch { return initialValue; }
  });
  const set = useCallback((v: T | ((prev: T) => T)) => {
    setValue((prev) => { const next = typeof v === "function" ? (v as (p: T) => T)(prev) : v; localStorage.setItem(key, JSON.stringify(next)); return next; });
  }, [key]);
  return [value, set] as const;
}
