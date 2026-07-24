import { useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Skeleton } from "@/components/ui/skeleton"
import { ArrowLeft, ExternalLink, HelpCircle, Loader2, Play, Trash2, Edit3, Wrench, Globe, Tag, Shield, Key, Activity } from "lucide-react"
import { useTool, useDeleteTool, useTestTool } from "@/hooks/use-tools-api"
import { toast } from "sonner"
import { formatDate } from "@/lib/utils"

const riskStyles: Record<string, string> = {
  low: "bg-green-500/10 text-green-600 dark:text-green-400 border-green-200 dark:border-green-800",
  medium: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-800",
  high: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-200 dark:border-red-800",
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
  const [deleteOpen, setDeleteOpen] = useState(false)

  if (isLoading) return <div className="flex items-center justify-center py-16"><div className="space-y-4 w-full max-w-2xl">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-24 w-full rounded-xl" />)}</div></div>
  if (!tool) return <div className="text-center py-16 text-muted-foreground"><Wrench size={48} className="mx-auto mb-4 opacity-30" /><p className="text-lg">Tool not found</p><Button variant="outline" className="mt-4" onClick={() => navigate("/tools")}>Back to Tools</Button></div>

  const handleTest = async () => {
    setTestLoading(true); setTestResult(null)
    testTool.mutate({ id: tool.id, input: {} }, {
      onSuccess: (d) => { setTestResult(JSON.stringify(d, null, 2)); setTestOpen(true) },
      onError: (err) => { setTestResult(`Error: ${err instanceof Error ? err.message : "Unknown"}`); setTestOpen(true) },
      onSettled: () => setTestLoading(false),
    })
  }

  const handleDelete = () => {
    deleteTool.mutate(tool.id, {
      onSuccess: () => { toast.success("Tool deleted"); navigate("/tools") },
      onError: () => toast.error("Failed to delete tool"),
    })
  }

  const meta = [
    { icon: Globe, label: "Endpoint", value: tool.endpoint_url, highlight: true },
    { icon: Activity, label: "Method", value: tool.http_method, badge: true },
    { icon: Shield, label: "Risk", value: tool.risk_level, badge: true, style: riskStyles[tool.risk_level] },
    { icon: Tag, label: "Category", value: tool.category },
    { icon: Key, label: "Auth", value: tool.auth_type || "none" },
    { icon: Wrench, label: "Version", value: `v${tool.version}` },
    { icon: Activity, label: "Status", value: tool.enabled ? "Active" : "Disabled", badge: true },
  ]

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <Button variant="ghost" size="icon" className="mt-1" onClick={() => navigate("/tools")}><ArrowLeft size={18} /></Button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-primary/10"><Wrench size={20} className="text-primary" /></div>
            <div>
              <h1 className="text-xl font-bold truncate">{tool.name}</h1>
              <p className="text-xs text-muted-foreground">v{tool.version} · Updated {formatDate(tool.updated_at)}</p>
            </div>
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
          <Tooltip><TooltipTrigger asChild><Button variant="outline" size="sm" onClick={handleTest} disabled={testLoading}>{testLoading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />} Test</Button></TooltipTrigger><TooltipContent>Send a test request</TooltipContent></Tooltip>
          <Tooltip><TooltipTrigger asChild><Button variant="outline" size="sm" onClick={() => navigate(`/tools/${tool.id}/edit`)}><Edit3 size={14} /> Edit</Button></TooltipTrigger><TooltipContent>Modify tool configuration</TooltipContent></Tooltip>
          <Tooltip><TooltipTrigger asChild><Button variant="destructive" size="sm" onClick={() => setDeleteOpen(true)}><Trash2 size={14} /> Delete</Button></TooltipTrigger><TooltipContent>Delete this tool permanently</TooltipContent></Tooltip>
        </div>
      </div>

      {/* Description + Meta grid */}
      <div className="grid gap-4 grid-cols-1 lg:grid-cols-3">
        <Card className="lg:col-span-2 card-hover">
          <CardHeader><CardTitle className="text-base">Description</CardTitle></CardHeader>
          <CardContent>
            <p className="text-sm">{tool.description || "No description provided."}</p>
            {tool.purpose && <><p className="text-sm font-medium mt-4 mb-1">Purpose</p><p className="text-sm text-muted-foreground">{tool.purpose}</p></>}
            {tool.tags?.length > 0 && <div className="flex flex-wrap gap-1.5 mt-4">{tool.tags.map((t) => <Badge key={t} variant="outline" className="text-[10px]">{t}</Badge>)}</div>}
            {tool.keywords?.length > 0 && <div className="flex flex-wrap gap-1.5 mt-3 pt-3 border-t"><span className="text-[10px] text-muted-foreground w-full mb-1">Keywords</span>{tool.keywords.map((k) => <Badge key={k} variant="secondary" className="text-[10px]">{k}</Badge>)}</div>}
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader><CardTitle className="text-base">Details</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {meta.map((m) => (
              <Tooltip key={m.label}><TooltipTrigger asChild>
                <div className="flex items-center justify-between text-sm cursor-help">
                  <span className="flex items-center gap-2 text-muted-foreground"><m.icon size={13} />{m.label}</span>
                  {m.badge ? <Badge className={`text-[10px] ${m.style || ""}`}>{m.value}</Badge> : m.highlight ? <code className="text-xs truncate max-w-[140px] bg-muted px-1.5 py-0.5 rounded">{m.value}</code> : <span className="font-medium">{m.value}</span>}
                </div>
              </TooltipTrigger><TooltipContent>{m.label} configuration</TooltipContent></Tooltip>
            ))}
            <Button variant="outline" size="sm" className="w-full mt-2 gap-2" onClick={() => window.open(tool.endpoint_url, "_blank")}><ExternalLink size={14} /> Open Endpoint</Button>
          </CardContent>
        </Card>
      </div>

      {/* Schema cards */}
      {[{ title: "Input Schema", data: tool.input_schema }, { title: "Output Schema", data: tool.output_schema }, { title: "Validation Rules", data: tool.validation_rules }].map((s) =>
        s.data && Object.keys(s.data).length > 0 && (
          <Card key={s.title} className="card-hover">
            <CardHeader><CardTitle className="text-base">{s.title}</CardTitle></CardHeader>
            <CardContent><pre className="text-xs bg-muted/50 p-4 rounded-lg overflow-auto max-h-60 border">{JSON.stringify(s.data, null, 2)}</pre></CardContent>
          </Card>
        )
      )}

      {/* Delete Dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent><DialogHeader><DialogTitle>Delete Tool</DialogTitle><DialogDescription>Are you sure you want to delete <strong>{tool.name}</strong>? This cannot be undone.</DialogDescription></DialogHeader>
          <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setDeleteOpen(false)}>Cancel</Button><Button variant="destructive" onClick={handleDelete} disabled={deleteTool.isPending}>{deleteTool.isPending ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />} Delete</Button></div>
        </DialogContent>
      </Dialog>

      {/* Test Dialog */}
      <Dialog open={testOpen} onOpenChange={setTestOpen}>
        <DialogContent className="max-w-2xl"><DialogHeader><DialogTitle>Test Result</DialogTitle><DialogDescription>Response from testing {tool.name}</DialogDescription></DialogHeader>
          <pre className="text-xs bg-muted/50 p-4 rounded-lg overflow-auto max-h-80 whitespace-pre-wrap border">{testResult}</pre>
        </DialogContent>
      </Dialog>
    </div>
  )
}
