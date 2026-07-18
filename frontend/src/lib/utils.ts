import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function formatDate(date: string | Date): string {
  const d = typeof date === "string" ? new Date(date) : date
  return d.toLocaleString()
}

export function copyToClipboard(text: string): Promise<void> {
  return navigator.clipboard.writeText(text)
}

export function downloadJson(data: unknown, filename: string): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function generateCurlCommand(
  method: string,
  url: string,
  headers: Record<string, string>,
  body?: unknown,
): string {
  const parts = [`curl -X ${method.toUpperCase()} "${url}"`]
  for (const [key, value] of Object.entries(headers)) {
    parts.push(`  -H "${key}: ${value}"`)
  }
  if (body) {
    parts.push(`  -d '${JSON.stringify(body)}'`)
  }
  return parts.join(" \\\n")
}
