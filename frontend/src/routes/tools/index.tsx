import { useNavigate } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Plus, Search, Loader2 } from "lucide-react"
import { useToolsList } from "@/hooks/use-tools-api"
import { useState } from "react"

const riskVariant: Record<string, "success" | "warning" | "destructive" | "secondary"> = {
  low: "success", medium: "warning", high: "destructive", critical: "destructive",
}

export default function ToolsListPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState("")
  const { data, isLoading } = useToolsList({ page_size: 100, enabled: true })

  const filtered = data?.items?.filter((t) =>
    t.name.toLowerCase().includes(search.toLowerCase()) ||
    t.description.toLowerCase().includes(search.toLowerCase())
  ) ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Tools</h1>
          <p className="text-muted-foreground text-sm">Registered tools and capabilities</p>
        </div>
        <Button onClick={() => navigate("/tools/new")}><Plus size={16} /> Create Tool</Button>
      </div>

      <div className="relative">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search tools..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9 max-w-sm"
        />
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-12"><Loader2 size={24} className="animate-spin text-muted-foreground" /></div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground text-sm">No tools found</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-muted-foreground text-xs uppercase">
                    <th className="text-left px-6 py-3 font-medium">Name</th>
                    <th className="text-left px-6 py-3 font-medium">Category</th>
                    <th className="text-left px-6 py-3 font-medium">Risk</th>
                    <th className="text-center px-6 py-3 font-medium">Status</th>
                    <th className="text-right px-6 py-3 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {filtered.map((tool) => (
                    <tr key={tool.id} className="hover:bg-muted/50 cursor-pointer transition-colors" onClick={() => navigate(`/tools/${tool.id}`)}>
                      <td className="px-6 py-3">
                        <p className="font-medium">{tool.name}</p>
                        <p className="text-xs text-muted-foreground truncate max-w-[300px]">{tool.description}</p>
                      </td>
                      <td className="px-6 py-3"><Badge variant="outline">{tool.category}</Badge></td>
                      <td className="px-6 py-3"><Badge variant={riskVariant[tool.risk_level] ?? "secondary"}>{tool.risk_level}</Badge></td>
                      <td className="px-6 py-3 text-center">
                        <span className={`inline-block w-2 h-2 rounded-full ${tool.enabled ? "bg-green-500" : "bg-gray-300"}`} />
                      </td>
                      <td className="px-6 py-3 text-right">
                        <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); navigate(`/tools/${tool.id}`) }}>View</Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
