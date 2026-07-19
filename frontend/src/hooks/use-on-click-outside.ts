import { useEffect, useRef, type RefObject } from "react";

export function useOnClickOutside<T extends HTMLElement>(handler: (event: MouseEvent | TouchEvent) => void): RefObject<T | null> {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    const listener = (event: MouseEvent | TouchEvent) => {
      if (!ref.current || ref.current.contains(event.target as Node)) return;
      handler(event);
    };
    document.addEventListener("mousedown", listener);
    document.addEventListener("touchstart", listener);
    return () => { document.removeEventListener("mousedown", listener); document.removeEventListener("touchstart", listener); };
  }, [handler]);
  return ref;
}
