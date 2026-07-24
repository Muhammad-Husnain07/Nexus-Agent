import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useToolsList } from "@/hooks/use-tools-api"
import { Wrench, Plus, Search, ArrowUpRight, HelpCircle } from "lucide-react"

const riskColor: Record<string, string> = { low: "bg-green-500/10 text-green-600 dark:text-green-400 border-green-200 dark:border-green-800", medium: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-800", high: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-200 dark:border-red-800" }

export default function ToolsListPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState("")
  const { data, isLoading } = useToolsList({ page_size: 100, enabled: true })
  const tools = (data?.items ?? []).filter((t) => t.name.toLowerCase().includes(search.toLowerCase()) || t.description.toLowerCase().includes(search.toLowerCase()) || (t.tags || []).some((tag) => tag.toLowerCase().includes(search.toLowerCase())))

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Tools</h1>
          <p className="text-sm text-muted-foreground">{data?.total ?? 0} registered tools</p>
        </div>
        <Button onClick={() => navigate("/tools/new")}><Plus size={16} /> Register Tool</Button>
      </div>

      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search tools..." className="pl-8" />
        </div>
      </div>

      {isLoading ? (
        <div className="grid gap-3 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
          {[...Array(6)].map((_, i) => (
            <Card key={i}><CardContent className="p-4"><Skeleton className="h-5 w-32 mb-2" /><Skeleton className="h-3 w-full mb-3" /><Skeleton className="h-4 w-20" /></CardContent></Card>
          ))}
        </div>
      ) : tools.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <Wrench size={40} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">{search ? "No tools match your search" : "No tools registered yet"}</p>
          {!search && <Button variant="outline" size="sm" className="mt-3" onClick={() => navigate("/tools/new")}>Register your first tool</Button>}
        </div>
      ) : (
        <div className="grid gap-3 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
          {tools.map((tool) => (
            <Card key={tool.id} className="card-hover cursor-pointer" onClick={() => navigate(`/tools/${tool.id}`)}>
              <CardContent className="p-4">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <div className="p-1.5 rounded-lg bg-primary/10 shrink-0"><Wrench size={14} className="text-primary" /></div>
                    <p className="text-sm font-medium truncate">{tool.name}</p>
                  </div>
                  <ArrowUpRight size={14} className="text-muted-foreground shrink-0 mt-1" />
                </div>
                <p className="text-xs text-muted-foreground line-clamp-2 mb-3">{tool.description || tool.purpose || "No description"}</p>
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="outline" className={`text-[10px] ${riskColor[tool.risk_level] || ""}`}>{tool.risk_level}</Badge>
                  <Badge variant="outline" className="text-[10px]">{tool.http_method}</Badge>
                  <Badge variant={tool.enabled ? "success" : "secondary"} className="text-[10px]">{tool.enabled ? "Active" : "Disabled"}</Badge>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
