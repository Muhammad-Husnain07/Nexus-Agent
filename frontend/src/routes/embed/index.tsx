import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Copy } from "lucide-react"

export default function EmbedPage() {
  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-bold tracking-tight">Embed Widget</h1>
      <Card>
        <CardHeader><CardTitle>Widget Configuration</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div><label className="text-sm font-medium">Widget Title</label><Input placeholder="Nexus Assistant" /></div>
          <div><label className="text-sm font-medium">Theme</label>
            <select className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm mt-1">
              <option>light</option><option>dark</option><option>auto</option>
            </select></div>
          <Button variant="outline"><Copy size={16} /> Copy Embed Code</Button>
        </CardContent>
      </Card>
    </div>
  )
}
