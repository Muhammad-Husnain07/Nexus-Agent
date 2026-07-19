import { useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Search } from "lucide-react"

const tabs = ["Episodic", "Semantic", "Procedural"]

export default function MemoryPage() {
  const [tab, setTab] = useState(0)

  return (
    <div className="space-y-6">
      <div><h1 className="text-2xl font-bold tracking-tight">Memory</h1></div>
      <div className="flex gap-2 border-b">
        {tabs.map((t, i) => (
          <button key={t} className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${i === tab ? "border-primary text-foreground" : "border-transparent text-muted-foreground"}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>
      <div className="relative max-w-sm"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" /><Input placeholder="Search memories..." className="pl-9" /></div>
      <Card><CardContent className="p-6 text-muted-foreground text-center">No memories found.</CardContent></Card>
    </div>
  )
}
