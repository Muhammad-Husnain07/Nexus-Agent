import { useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Search, Loader2, Trash2, BrainCircuit } from "lucide-react"
import { useMemories, useDeleteMemory } from "@/hooks/use-memory"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { formatDate } from "@/lib/utils"

const tabs = ["episodic", "semantic", "procedural"]

export default function MemoryPage() {
  const [tab, setTab] = useState("episodic")
  const [search, setSearch] = useState("")
  const { data: memories, isLoading, refetch } = useMemories(search ? { q: search, kind: tab } : { kind: tab })
  const deleteMemory = useDeleteMemory()

  const list = Array.isArray(memories) ? memories : []

  const handleDelete = (id: string) => {
    deleteMemory.mutate(id, {
      onSuccess: () => { toast.success("Memory deleted"); refetch() },
      onError: () => toast.error("Failed to delete memory"),
    })
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Memory</h1>
        <p className="text-muted-foreground text-sm">Long-term agent memory</p>
      </div>

      <div className="flex gap-1 bg-muted rounded-lg p-1 w-fit">
        {tabs.map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={cn("px-4 py-1.5 text-sm rounded-md transition-colors capitalize", tab === t ? "bg-background shadow-sm font-medium" : "text-muted-foreground hover:text-foreground")}>
            {t}
          </button>
        ))}
      </div>

      <div className="relative">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input placeholder="Search memories..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9 max-w-sm" />
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-12"><Loader2 size={24} className="animate-spin text-muted-foreground" /></div>
          ) : list.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <BrainCircuit size={32} className="mb-2 opacity-50" />
              <p className="text-sm">No {tab} memories found</p>
            </div>
          ) : (
            <div className="divide-y">
              {list.map((m: any) => (
                <div key={m.id} className="px-6 py-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm">{m.content}</p>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-xs text-muted-foreground">Importance: {(m.importance ?? 0).toFixed(2)}</span>
                        <span className="text-xs text-muted-foreground">{formatDate(m.created_at)}</span>
                        {m.session_id && <span className="text-xs text-muted-foreground truncate">Session: {m.session_id.slice(0, 8)}...</span>}
                      </div>
                    </div>
                    <Button variant="ghost" size="icon" className="shrink-0 text-muted-foreground hover:text-destructive" onClick={() => handleDelete(m.id)}>
                      <Trash2 size={14} />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
