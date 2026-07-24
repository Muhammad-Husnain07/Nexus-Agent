import { useState, useEffect } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { ArrowLeft, Loader2, HelpCircle } from "lucide-react"
import { useCreateTool, useTool, useUpdateTool } from "@/hooks/use-tools-api"
import { toast } from "sonner"
import { cn } from "@/lib/utils"

const steps = ["Basic Info", "API Config", "Input Schema", "Review"]

export default function ToolNewPage() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const isEdit = !!id
  const { data: existingTool, isLoading: toolLoading } = useTool(id ?? "", { enabled: isEdit })
  const createTool = useCreateTool()
  const updateTool = useUpdateTool()

  const [step, setStep] = useState(0)
  const [form, setForm] = useState({
    name: "", description: "", purpose: "",
    endpoint_url: "", http_method: "GET", auth_type: "none",
    input_schema: "", output_schema: "",
    tags: "", category: "general",
    risk_level: "low", enabled: true,
    keywords: "", aliases: "",
  })

  useEffect(() => {
    if (existingTool) {
      setForm({
        name: existingTool.name,
        description: existingTool.description,
        purpose: existingTool.purpose,
        endpoint_url: existingTool.endpoint_url,
        http_method: existingTool.http_method,
        auth_type: existingTool.auth_type,
        input_schema: JSON.stringify(existingTool.input_schema, null, 2),
        output_schema: JSON.stringify(existingTool.output_schema, null, 2),
        tags: (existingTool.tags || []).join(", "),
        category: existingTool.category,
        risk_level: existingTool.risk_level,
        enabled: existingTool.enabled,
        keywords: (existingTool.keywords || []).join(", "),
        aliases: (existingTool.aliases || []).join(", "),
      })
    }
  }, [existingTool])

  const update = (field: string, value: string | boolean) => setForm((f) => ({ ...f, [field]: value }))

  const handleSubmit = async () => {
    if (!form.name.trim()) { toast.error("Tool name is required"); return }
    if (!form.endpoint_url.trim()) { toast.error("Endpoint URL is required"); return }

    const tags = form.tags.split(",").map((t) => t.trim()).filter(Boolean)
    const keywords = form.keywords.split(",").map((t) => t.trim()).filter(Boolean)
    const aliases = form.aliases.split(",").map((t) => t.trim()).filter(Boolean)

    let input_schema: Record<string, unknown> = {}
    let output_schema: Record<string, unknown> = {}
    try { input_schema = form.input_schema ? JSON.parse(form.input_schema) : {} } catch { toast.error("Invalid Input Schema JSON"); return }
    try { output_schema = form.output_schema ? JSON.parse(form.output_schema) : {} } catch { toast.error("Invalid Output Schema JSON"); return }

    const payload = {
      name: form.name.trim(),
      description: form.description.trim(),
      purpose: form.purpose.trim(),
      endpoint_url: form.endpoint_url.trim(),
      http_method: form.http_method,
      auth_type: form.auth_type,
      input_schema,
      output_schema,
      tags,
      category: form.category,
      risk_level: form.risk_level,
      enabled: form.enabled,
      keywords,
      aliases,
    }

    try {
      if (isEdit && id) {
        await updateTool.mutateAsync({ id, ...payload })
        toast.success("Tool updated")
      } else {
        await createTool.mutateAsync(payload as any)
        toast.success("Tool created")
      }
      navigate("/tools")
    } catch {
      toast.error(isEdit ? "Failed to update tool" : "Failed to create tool")
    }
  }

  if (isEdit && toolLoading) {
    return <div className="flex items-center justify-center py-12"><Loader2 size={24} className="animate-spin text-muted-foreground" /></div>
  }

  return (
    <div className="max-w-2xl mx-auto space-y-4">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => navigate("/tools")}><ArrowLeft size={18} /></Button>
        <h1 className="text-xl font-bold">{isEdit ? "Edit Tool" : "Register Tool"}</h1>
      </div>

      <div className="flex items-center gap-2 mb-4">
        {steps.map((s, i) => (
          <div key={i} className="flex items-center gap-2">
            <Badge variant={step >= i ? "default" : "outline"} className={cn("h-6 w-6 p-0 rounded-full", step >= i && "bg-primary")}>{i + 1}</Badge>
            <span className={cn("text-xs", step >= i ? "text-foreground" : "text-muted-foreground")}>{s}</span>
            {i < steps.length - 1 && <div className="w-8 h-px bg-border" />}
          </div>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">{steps[step]}
            <Tooltip><TooltipTrigger><HelpCircle size={14} className="text-muted-foreground" /></TooltipTrigger>
            <TooltipContent>{["Enter basic tool identification", "Configure API endpoint", "Define JSON schemas", "Review and save"][step]}</TooltipContent></Tooltip>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {step === 0 && (
            <>
              <div>
                <Label htmlFor="name">Tool Name *</Label>
                <Input id="name" value={form.name} onChange={(e) => update("name", e.target.value)} placeholder="e.g. get_weather" />
              </div>
              <div>
                <Label htmlFor="desc">Description</Label>
                <textarea id="desc" value={form.description} onChange={(e) => update("description", e.target.value)} placeholder="What does this tool do?"
                  className="flex min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring" />
              </div>
              <div>
                <Label htmlFor="purpose">Purpose</Label>
                <textarea id="purpose" value={form.purpose} onChange={(e) => update("purpose", e.target.value)} placeholder="When to use this tool"
                  className="flex min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring" />
              </div>
            </>
          )}
          {step === 1 && (
            <>
              <div>
                <Label htmlFor="url">Endpoint URL *</Label>
                <Input id="url" value={form.endpoint_url} onChange={(e) => update("endpoint_url", e.target.value)} placeholder="https://api.example.com/v1/endpoint" />
              </div>
              <div>
                <Label htmlFor="method">HTTP Method</Label>
                <select id="method" value={form.http_method} onChange={(e) => update("http_method", e.target.value)}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring">
                  {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <div>
                <Label htmlFor="auth">Auth Type</Label>
                <select id="auth" value={form.auth_type} onChange={(e) => update("auth_type", e.target.value)}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring">
                  {["none", "api_key", "bearer", "basic"].map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
              </div>
            </>
          )}
          {step === 2 && (
            <>
              <div>
                <Label htmlFor="inputSchema">Input Schema (JSON)</Label>
                <textarea id="inputSchema" value={form.input_schema} onChange={(e) => update("input_schema", e.target.value)} placeholder='{"type":"object","properties":{}}'
                  className="flex min-h-[120px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono shadow-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring" />
              </div>
              <div>
                <Label htmlFor="outputSchema">Output Schema (JSON)</Label>
                <textarea id="outputSchema" value={form.output_schema} onChange={(e) => update("output_schema", e.target.value)} placeholder='{"type":"object","properties":{}}'
                  className="flex min-h-[120px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono shadow-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring" />
              </div>
            </>
          )}
          {step === 3 && (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-muted-foreground">Name</span><span>{form.name || "(not set)"}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Endpoint</span><code className="text-xs">{form.endpoint_url || "(not set)"}</code></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Method</span><Badge variant="outline">{form.http_method}</Badge></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Category</span><Badge variant="outline">{form.category}</Badge></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Risk</span><Badge variant="outline">{form.risk_level}</Badge></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Enabled</span><Badge variant={form.enabled ? "success" : "secondary"}>{form.enabled ? "Yes" : "No"}</Badge></div>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex justify-between">
        <Button variant="outline" onClick={() => step > 0 ? setStep(step - 1) : navigate("/tools")} disabled={step === 0 && createTool.isPending}>
          {step > 0 ? "Previous" : "Cancel"}
        </Button>
        {step < 3 ? (
          <Button onClick={() => setStep(step + 1)}>Next</Button>
        ) : (
          <Button onClick={handleSubmit} disabled={createTool.isPending || updateTool.isPending}>
            {createTool.isPending || updateTool.isPending ? <Loader2 size={14} className="animate-spin" /> : null}
            {isEdit ? "Update Tool" : "Create Tool"}
          </Button>
        )}
      </div>
    </div>
  )
}
