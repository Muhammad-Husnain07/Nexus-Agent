import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Play, Loader2, HelpCircle, Globe, Server } from "lucide-react"

export default function PlaygroundPage() {
  const [method, setMethod] = useState("GET")
  const [url, setUrl] = useState("")
  const [body, setBody] = useState("")
  const [response, setResponse] = useState("")
  const [status, setStatus] = useState<number | null>(null)
  const [timing, setTiming] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSend = async () => {
    if (!url.trim()) return
    setLoading(true); setResponse(""); setStatus(null)
    const start = performance.now()
    try {
      const opts: RequestInit = { method }
      if (method !== "GET" && method !== "HEAD" && body.trim()) {
        opts.headers = { "Content-Type": "application/json" }
        opts.body = body
      }
      const res = await fetch(url, opts)
      setStatus(res.status)
      const text = await res.text()
      try { setResponse(JSON.stringify(JSON.parse(text), null, 2)) } catch { setResponse(text) }
    } catch (err) {
      setStatus(0)
      setResponse(`Error: ${err instanceof Error ? err.message : "Request failed"}`)
    }
    setTiming(Math.round(performance.now() - start))
    setLoading(false)
  }

  const methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold">API Playground</h1>
        <p className="text-sm text-muted-foreground">Test API endpoints directly</p>
      </div>

      <Card className="card-hover">
        <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Globe size={16} /> Request</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <select value={method} onChange={(e) => setMethod(e.target.value)}
              className="h-9 w-24 rounded-lg border border-input bg-transparent px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring shrink-0">
              {methods.map((m) => <option key={m}>{m}</option>)}
            </select>
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://api.example.com/endpoint" className="flex-1" />
            <Tooltip><TooltipTrigger asChild><Button onClick={handleSend} disabled={loading || !url.trim()}>{loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />} Send</Button></TooltipTrigger><TooltipContent>Execute the request</TooltipContent></Tooltip>
          </div>

          {(method === "POST" || method === "PUT" || method === "PATCH") && (
            <div><p className="text-xs font-medium mb-1">Request Body</p>
              <textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder='{"key": "value"}'
                className="flex min-h-[100px] w-full rounded-lg border border-input bg-transparent px-3 py-2 text-sm font-mono placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring" />
            </div>
          )}
        </CardContent>
      </Card>

      {response && (
        <Card className="card-hover">
          <CardHeader>
            <CardTitle className="flex items-center justify-between text-base">
              <span className="flex items-center gap-2"><Server size={16} /> Response</span>
              <div className="flex items-center gap-2">
                {status && <Badge variant={status < 400 ? "success" : "destructive"}>{status}</Badge>}
                {timing !== null && <span className="text-xs text-muted-foreground">{timing}ms</span>}
              </div>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted/50 p-4 rounded-lg overflow-auto max-h-80 border whitespace-pre-wrap">{response}</pre>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
