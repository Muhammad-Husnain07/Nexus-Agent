import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function truncate(str: string, max: number) {
  return str.length > max ? str.slice(0, max) + "..." : str
}

export function formatDate(date: string) {
  return new Date(date).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  })
}

export function formatTime(date: string) {
  return new Date(date).toLocaleTimeString("en-US", {
    hour: "2-digit", minute: "2-digit",
  })
}
