type MessageHandler = (data: unknown) => void

export class WebSocketManager {
  private ws: WebSocket | null = null
  private url: string
  private handlers = new Map<string, Set<MessageHandler>>()
  private reconnectAttempts = 0
  private maxReconnectAttempts = 10
  private reconnectDelay = 1000
  private token: string | null = null

  constructor(url: string, token?: string) {
    this.url = url
    this.token = token ?? null
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return

    const wsUrl = this.token ? `${this.url}?token=${this.token}` : this.url
    this.ws = new WebSocket(wsUrl)

    this.ws.onopen = () => {
      this.reconnectAttempts = 0
    }

    this.ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data)
        const type = parsed.type || "message"
        const typeHandlers = this.handlers.get(type)
        if (typeHandlers) {
          typeHandlers.forEach((handler) => handler(parsed))
        }
        const wildcardHandlers = this.handlers.get("*")
        if (wildcardHandlers) {
          wildcardHandlers.forEach((handler) => handler(parsed))
        }
      } catch {
        const messageHandlers = this.handlers.get("message")
        if (messageHandlers) {
          messageHandlers.forEach((handler) => handler(event.data))
        }
      }
    }

    this.ws.onclose = () => {
      this.scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts)
    this.reconnectAttempts++
    setTimeout(() => this.connect(), delay)
  }

  send(type: string, payload: Record<string, unknown> = {}): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, ...payload }))
    }
  }

  on(type: string, handler: MessageHandler): () => void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set())
    }
    this.handlers.get(type)!.add(handler)
    return () => {
      this.handlers.get(type)?.delete(handler)
    }
  }

  disconnect(): void {
    this.reconnectAttempts = this.maxReconnectAttempts
    this.ws?.close()
    this.ws = null
  }
}
