import { useParams, useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ArrowLeft, ExternalLink, Loader2, Trash2 } from "lucide-react"
import { useTool, useDeleteTool } from "@/hooks/use-tools-api"
import { toast } from "sonner"
import { formatDate } from "@/lib/utils"

const riskVariant: Record<string, "success" | "warning" | "destructive" | "secondary"> = {
  low: "success", medium: "warning", high: "destructive", critical: "destructive",
}

export default function ToolDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: tool, isLoading } = useTool(id!)
  const deleteTool = useDeleteTool()

  if (isLoading) {
    return <div className="flex items-center justify-center py-12"><Loader2 size={24} className="animate-spin text-muted-foreground" /></div>
  }

  if (!tool) {
    return (
      <div className="text-center py-12">
        <p className="text-muted-foreground">Tool not found</p>
        <Button variant="outline" className="mt-4" onClick={() => navigate("/tools")}>Back to Tools</Button>
      </div>
    )
  }

  const handleDelete = () => {
    deleteTool.mutate(tool.id, {
      onSuccess: () => { toast.success("Tool deleted"); navigate("/tools") },
      onError: () => toast.error("Failed to delete tool"),
    })
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => navigate("/tools")}><ArrowLeft size={18} /></Button>
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-bold truncate">{tool.name}</h1>
          <p className="text-xs text-muted-foreground">v{tool.version} · Updated {formatDate(tool.updated_at)}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => navigate(`/tools/${tool.id}/edit`)}>Edit</Button>
        <Button variant="destructive" size="sm" onClick={handleDelete}><Trash2 size={14} /> Delete</Button>
      </div>

      <div className="grid gap-4 grid-cols-1 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Description</CardTitle></CardHeader>
          <CardContent>
            <p className="text-sm">{tool.description || "No description"}</p>
            {tool.purpose && (
              <>
                <p className="text-sm font-medium mt-4 mb-1">Purpose</p>
                <p className="text-sm text-muted-foreground">{tool.purpose}</p>
              </>
            )}
            {tool.tags?.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-4">
                {tool.tags.map((t) => <Badge key={t} variant="outline">{t}</Badge>)}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Details</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Category</span><Badge variant="outline">{tool.category}</Badge></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Risk</span><Badge variant={riskVariant[tool.risk_level] ?? "secondary"}>{tool.risk_level}</Badge></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Endpoint</span><code className="text-xs truncate max-w-[150px]">{tool.endpoint_url}</code></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Method</span><Badge variant="outline">{tool.http_method}</Badge></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Status</span><Badge variant={tool.enabled ? "success" : "secondary"}>{tool.enabled ? "Enabled" : "Disabled"}</Badge></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Approval</span><Badge variant={tool.requires_approval ? "warning" : "success"}>{tool.requires_approval ? "Required" : "None"}</Badge></div>
            <Button variant="outline" size="sm" className="w-full mt-2" onClick={() => window.open(tool.endpoint_url, "_blank")}>
              <ExternalLink size={14} /> Test Endpoint
            </Button>
          </CardContent>
        </Card>
      </div>

      {tool.input_schema && Object.keys(tool.input_schema).length > 0 && (
        <Card>
          <CardHeader><CardTitle>Input Schema</CardTitle></CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-4 rounded-lg overflow-auto max-h-60">{JSON.stringify(tool.input_schema, null, 2)}</pre>
          </CardContent>
        </Card>
      )}

      {tool.output_schema && Object.keys(tool.output_schema).length > 0 && (
        <Card>
          <CardHeader><CardTitle>Output Schema</CardTitle></CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-4 rounded-lg overflow-auto max-h-60">{JSON.stringify(tool.output_schema, null, 2)}</pre>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
