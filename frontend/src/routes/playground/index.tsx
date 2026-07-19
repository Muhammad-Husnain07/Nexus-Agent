import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Play } from "lucide-react"

export default function PlaygroundPage() {
  const [method, setMethod] = useState("GET")
  const [url, setUrl] = useState("")

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Test Playground</h1>
      <Card>
        <CardHeader><CardTitle>Request</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <select className="h-10 rounded-md border border-input bg-background px-3 text-sm w-24" value={method} onChange={(e) => setMethod(e.target.value)}>
              <option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option>
            </select>
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://api.example.com/endpoint" className="flex-1" />
            <Button><Play size={16} /> Send</Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Response</CardTitle></CardHeader>
        <CardContent><div className="min-h-[200px] rounded-md bg-muted p-4 text-sm font-mono text-muted-foreground">Response will appear here</div></CardContent>
      </Card>
    </div>
  )
}
