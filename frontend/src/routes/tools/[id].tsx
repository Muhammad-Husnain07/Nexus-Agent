import { useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { ArrowLeft, ExternalLink, HelpCircle, Loader2, Play, Trash2 } from "lucide-react"
import { useTool, useDeleteTool, useTestTool } from "@/hooks/use-tools-api"
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
  const testTool = useTestTool()
  const [testResult, setTestResult] = useState<string | null>(null)
  const [testOpen, setTestOpen] = useState(false)
  const [testLoading, setTestLoading] = useState(false)

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

  const handleTest = async () => {
    setTestLoading(true)
    setTestResult(null)
    testTool.mutate(tool.id, {
      onSuccess: (data) => {
        setTestResult(JSON.stringify(data, null, 2))
        setTestOpen(true)
      },
      onError: (err) => {
        setTestResult(`Error: ${err instanceof Error ? err.message : "Unknown error"}`)
        setTestOpen(true)
      },
      onSettled: () => setTestLoading(false),
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
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="outline" size="sm" onClick={handleTest} disabled={testLoading}>
              {testLoading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              Test
            </Button>
          </TooltipTrigger>
          <TooltipContent>Send a test request to this tool's endpoint</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="outline" size="sm" onClick={() => navigate(`/tools/${tool.id}/edit`)}>Edit</Button>
          </TooltipTrigger>
          <TooltipContent>Modify tool configuration</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="destructive" size="sm" onClick={handleDelete}><Trash2 size={14} /> Delete</Button>
          </TooltipTrigger>
          <TooltipContent>Permanently delete this tool</TooltipContent>
        </Tooltip>
      </div>

      <div className="grid gap-4 grid-cols-1 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Description
              <Tooltip>
                <TooltipTrigger><HelpCircle size={14} className="text-muted-foreground" /></TooltipTrigger>
                <TooltipContent>What this tool does and when to use it</TooltipContent>
              </Tooltip>
            </CardTitle>
          </CardHeader>
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
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex justify-between cursor-help"><span className="text-muted-foreground">Category</span><Badge variant="outline">{tool.category}</Badge></div>
              </TooltipTrigger>
              <TooltipContent>Functional category for grouping tools</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex justify-between cursor-help"><span className="text-muted-foreground">Risk</span><Badge variant={riskVariant[tool.risk_level] ?? "secondary"}>{tool.risk_level}</Badge></div>
              </TooltipTrigger>
              <TooltipContent>Risk level determines execution safeguards</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex justify-between cursor-help"><span className="text-muted-foreground">Endpoint</span><code className="text-xs truncate max-w-[150px]">{tool.endpoint_url}</code></div>
              </TooltipTrigger>
              <TooltipContent>The API URL this tool calls</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex justify-between cursor-help"><span className="text-muted-foreground">Method</span><Badge variant="outline">{tool.http_method}</Badge></div>
              </TooltipTrigger>
              <TooltipContent>HTTP method used for the API request</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex justify-between cursor-help"><span className="text-muted-foreground">Status</span><Badge variant={tool.enabled ? "success" : "secondary"}>{tool.enabled ? "Enabled" : "Disabled"}</Badge></div>
              </TooltipTrigger>
              <TooltipContent>Whether the tool is active for agent use</TooltipContent>
            </Tooltip>
            {tool.keywords && tool.keywords.length > 0 && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex flex-wrap gap-1 pt-2 border-t"><span className="text-xs text-muted-foreground w-full mb-1">Keywords</span>{tool.keywords.slice(0, 8).map((k) => <Badge key={k} variant="secondary" className="text-[10px]">{k}</Badge>)}</div>
                </TooltipTrigger>
                <TooltipContent>Keywords used for dynamic tool matching</TooltipContent>
              </Tooltip>
            )}
            <Button variant="outline" size="sm" className="w-full mt-2" onClick={() => window.open(tool.endpoint_url, "_blank")}>
              <ExternalLink size={14} /> Open Endpoint
            </Button>
          </CardContent>
        </Card>
      </div>

      {tool.input_schema && Object.keys(tool.input_schema).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Input Schema
              <Tooltip>
                <TooltipTrigger><HelpCircle size={14} className="text-muted-foreground" /></TooltipTrigger>
                <TooltipContent>JSON Schema defining the expected input parameters</TooltipContent>
              </Tooltip>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-4 rounded-lg overflow-auto max-h-60">{JSON.stringify(tool.input_schema, null, 2)}</pre>
          </CardContent>
        </Card>
      )}

      {tool.output_schema && Object.keys(tool.output_schema).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Output Schema
              <Tooltip>
                <TooltipTrigger><HelpCircle size={14} className="text-muted-foreground" /></TooltipTrigger>
                <TooltipContent>JSON Schema defining the expected response structure</TooltipContent>
              </Tooltip>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-4 rounded-lg overflow-auto max-h-60">{JSON.stringify(tool.output_schema, null, 2)}</pre>
          </CardContent>
        </Card>
      )}

      {tool.validation_rules && Object.keys(tool.validation_rules).length > 0 && (
        <Card>
          <CardHeader><CardTitle>Validation Rules</CardTitle></CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-4 rounded-lg overflow-auto max-h-60">{JSON.stringify(tool.validation_rules, null, 2)}</pre>
          </CardContent>
        </Card>
      )}

      <Dialog open={testOpen} onOpenChange={setTestOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Test Result</DialogTitle>
            <DialogDescription>Response from testing {tool.name}</DialogDescription>
          </DialogHeader>
          <pre className="text-xs bg-muted p-4 rounded-lg overflow-auto max-h-80 whitespace-pre-wrap">{testResult}</pre>
        </DialogContent>
      </Dialog>
    </div>
  )
}
