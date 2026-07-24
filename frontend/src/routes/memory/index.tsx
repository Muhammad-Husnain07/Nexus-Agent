import { useState } from "react"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useMemories, useDeleteMemory } from "@/hooks/use-memory"
import { BrainCircuit, Search, Trash2, HelpCircle, Loader2 } from "lucide-react"
import { formatDate } from "@/lib/utils"
import { toast } from "sonner"

const TABS = ["all", "episodic", "semantic", "procedural"]

export default function MemoryPage() {
  const [tab, setTab] = useState("all")
  const [search, setSearch] = useState("")
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const { data: memories, isLoading } = useMemories({ q: search || undefined, kind: tab === "all" ? undefined : tab })
  const deleteMemory = useDeleteMemory()
  const items = Array.isArray(memories) ? memories : []

  const handleDelete = async (id: string) => {
    try {
      await deleteMemory.mutateAsync(id)
      toast.success("Memory deleted")
      setDeleteConfirm(null)
    } catch { toast.error("Failed to delete memory") }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Memory</h1>
          <p className="text-sm text-muted-foreground">{items.length} stored memories</p>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          {TABS.map((t) => <TabsTrigger key={t} value={t} className="capitalize">{t}</TabsTrigger>)}
        </TabsList>

        {TABS.map((t) => (
          <TabsContent key={t} value={t}>
            <div className="relative max-w-md mb-4">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search memories..." className="pl-8" />
            </div>

            {isLoading ? (
              <div className="space-y-2">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-20 w-full rounded-lg" />)}</div>
            ) : items.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                <BrainCircuit size={40} className="mx-auto mb-3 opacity-30" />
                <p className="text-sm">{search ? "No memories match your search" : "No memories stored yet"}</p>
                <p className="text-xs mt-1">Memories are created automatically during conversations</p>
              </div>
            ) : (
              <div className="space-y-2">
                {items.map((mem) => (
                  <Card key={mem.id} className="card-hover">
                    <CardContent className="p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1.5">
                            <Badge variant="outline" className="text-[10px] capitalize">{mem.kind}</Badge>
                            <Tooltip>
                              <TooltipTrigger><span className="text-xs text-muted-foreground cursor-help">Importance: {(mem.importance || 0).toFixed(1)}</span></TooltipTrigger>
                              <TooltipContent>Memory importance score (0-1)</TooltipContent>
                            </Tooltip>
                          </div>
                          <p className="text-sm">{mem.content}</p>
                          <div className="flex items-center gap-2 mt-2 text-[10px] text-muted-foreground">
                            <span>{formatDate(mem.created_at)}</span>
                            {mem.session_id && <span>· Session: {mem.session_id.slice(0, 8)}...</span>}
                          </div>
                        </div>
                        <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0 opacity-60 hover:opacity-100" onClick={() => setDeleteConfirm(mem.id)}>
                          <Trash2 size={14} />
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </TabsContent>
        ))}
      </Tabs>

      <Dialog open={!!deleteConfirm} onOpenChange={() => setDeleteConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Memory</DialogTitle>
            <DialogDescription>Are you sure you want to delete this memory? This action cannot be undone.</DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDeleteConfirm(null)}>Cancel</Button>
            <Button variant="destructive" onClick={() => handleDelete(deleteConfirm!)} disabled={deleteMemory.isPending}>
              {deleteMemory.isPending ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />} Delete
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
