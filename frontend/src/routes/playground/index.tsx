import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Play, Loader2 } from "lucide-react"
import { toast } from "sonner"

export default function PlaygroundPage() {
  const [method, setMethod] = useState("GET")
  const [url, setUrl] = useState("")
  const [body, setBody] = useState("")
  const [response, setResponse] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]

  const handleSend = async () => {
    if (!url.trim()) { toast.error("URL is required"); return }
    setLoading(true)
    setResponse(null)

    try {
      const options: RequestInit = { method }
      if (method !== "GET" && method !== "DELETE" && body.trim()) {
        options.headers = { "Content-Type": "application/json" }
        options.body = body
      }
      const start = performance.now()
      const res = await fetch(url, options)
      const duration = Math.round(performance.now() - start)
      const text = await res.text()
      const contentType = res.headers.get("content-type") || ""
      let formatted = text
      if (contentType.includes("application/json")) {
        try { formatted = JSON.stringify(JSON.parse(text), null, 2) } catch { /* raw */ }
      }
      setResponse(`// ${res.status} ${res.statusText} (${duration}ms)\n\n${formatted}`)
    } catch (err: unknown) {
      setResponse(`// Error\n\n${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">API Playground</h1>
        <p className="text-muted-foreground text-sm">Test API endpoints directly</p>
      </div>

      <Card>
        <CardHeader><CardTitle>Request</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <select value={method} onChange={(e) => setMethod(e.target.value)}
              className="h-10 w-24 rounded-md border border-input bg-transparent px-3 py-2 text-sm font-medium">
              {methods.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="/api/v1/tools or full URL" className="flex-1 font-mono text-sm" />
            <Button onClick={handleSend} disabled={loading}>
              {loading ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
              Send
            </Button>
          </div>
          {method !== "GET" && method !== "DELETE" && (
            <textarea value={body} onChange={(e) => setBody(e.target.value)}
              className="flex min-h-[100px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono"
              placeholder='{"key": "value"}' />
          )}
        </CardContent>
      </Card>

      {response !== null && (
        <Card>
          <CardHeader><CardTitle>Response</CardTitle></CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-4 rounded-lg overflow-auto max-h-96 whitespace-pre-wrap font-mono">{response}</pre>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
