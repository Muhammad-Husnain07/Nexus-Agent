import { useEffect, useRef, useCallback } from "react"
import { WebSocketManager } from "@/lib/websocket"
import { useAuthStore } from "@/hooks/use-auth"

const wsInstances = new Map<string, WebSocketManager>()

export function useWebSocket(sessionId?: string) {
  const token = useAuthStore((s) => s.token)
  const wsRef = useRef<WebSocketManager | null>(null)

  const url = import.meta.env.VITE_WS_URL || `ws://${window.location.host}/ws`

  useEffect(() => {
    if (!sessionId) return

    const key = `${url}/${sessionId}`
    if (!wsInstances.has(key)) {
      const mgr = new WebSocketManager(key, token ?? undefined)
      wsInstances.set(key, mgr)
    }
    const mgr = wsInstances.get(key)!
    wsRef.current = mgr
    mgr.connect()

    return () => {
      // Don't disconnect — keep alive for the session
    }
  }, [url, sessionId, token])

  const send = useCallback(
    (type: string, payload?: Record<string, unknown>) => {
      wsRef.current?.send(type, payload)
    },
    [],
  )

  const on = useCallback(
    (type: string, handler: (data: unknown) => void) => {
      return wsRef.current?.on(type, handler) ?? (() => {})
    },
    [],
  )

  return { send, on }
}
