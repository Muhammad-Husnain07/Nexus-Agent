import { useState, useEffect } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { ArrowLeft, Loader2, HelpCircle, Wrench, CheckCircle, ArrowRight } from "lucide-react"
import { useCreateTool, useTool, useUpdateTool } from "@/hooks/use-tools-api"
import { toast } from "sonner"
import { cn } from "@/lib/utils"

const steps = ["Basic Info", "API Config", "Schema", "Review"]

export default function ToolNewPage() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const isEdit = !!id
  const { data: existingTool, isLoading: toolLoading } = useTool(id ?? "", { enabled: isEdit })
  const createTool = useCreateTool()
  const updateTool = useUpdateTool()

  const [step, setStep] = useState(0)
  const [form, setForm] = useState({ name: "", description: "", purpose: "", endpoint_url: "", http_method: "GET", auth_type: "none", input_schema: "", output_schema: "", tags: "", category: "general", risk_level: "low", enabled: true, keywords: "", aliases: "" })

  useEffect(() => {
    if (existingTool) setForm({
      name: existingTool.name, description: existingTool.description, purpose: existingTool.purpose,
      endpoint_url: existingTool.endpoint_url, http_method: existingTool.http_method, auth_type: existingTool.auth_type,
      input_schema: JSON.stringify(existingTool.input_schema, null, 2), output_schema: JSON.stringify(existingTool.output_schema, null, 2),
      tags: (existingTool.tags || []).join(", "), category: existingTool.category, risk_level: existingTool.risk_level,
      enabled: existingTool.enabled, keywords: (existingTool.keywords || []).join(", "), aliases: (existingTool.aliases || []).join(", "),
    })
  }, [existingTool])

  const update = (f: string, v: string | boolean) => setForm((s) => ({ ...s, [f]: v }))

  const handleSubmit = async () => {
    if (!form.name.trim()) { toast.error("Tool name is required"); return }
    if (!form.endpoint_url.trim()) { toast.error("Endpoint URL is required"); return }
    let input_schema: Record<string, unknown> = {}, output_schema: Record<string, unknown> = {}
    try { input_schema = form.input_schema ? JSON.parse(form.input_schema) : {} } catch { toast.error("Invalid Input Schema JSON"); return }
    try { output_schema = form.output_schema ? JSON.parse(form.output_schema) : {} } catch { toast.error("Invalid Output Schema JSON"); return }
    const payload = { name: form.name.trim(), description: form.description.trim(), purpose: form.purpose.trim(), endpoint_url: form.endpoint_url.trim(), http_method: form.http_method, auth_type: form.auth_type, input_schema, output_schema, tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean), category: form.category, risk_level: form.risk_level, enabled: form.enabled, keywords: form.keywords.split(",").map((t) => t.trim()).filter(Boolean), aliases: form.aliases.split(",").map((t) => t.trim()).filter(Boolean) }
    try { isEdit && id ? (await updateTool.mutateAsync({ id, ...payload }), toast.success("Tool updated")) : (await createTool.mutateAsync(payload as any), toast.success("Tool created")); navigate("/tools") }
    catch { toast.error(isEdit ? "Failed to update tool" : "Failed to create tool") }
  }

  if (isEdit && toolLoading) return <div className="flex items-center justify-center py-16"><div className="space-y-4 w-full max-w-md">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-20 w-full rounded-xl" />)}</div></div>

  return (
    <div className="max-w-xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => navigate("/tools")}><ArrowLeft size={18} /></Button>
        <div className="p-2 rounded-xl bg-primary/10"><Wrench size={18} className="text-primary" /></div>
        <h1 className="text-xl font-bold">{isEdit ? "Edit Tool" : "Register Tool"}</h1>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-0">
        {steps.map((s, i) => (
          <div key={i} className="flex items-center flex-1">
            <div className={cn("flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-colors", step >= i ? "bg-primary/10 text-primary" : "text-muted-foreground")}>
              {step > i ? <CheckCircle size={14} /> : <span className="w-5 h-5 rounded-full bg-muted flex items-center justify-center text-[10px]">{i + 1}</span>}
              <span className="hidden sm:inline">{s}</span>
            </div>
            {i < steps.length - 1 && <div className={cn("flex-1 h-px mx-2", step > i ? "bg-primary/30" : "bg-border")} />}
          </div>
        ))}
      </div>

      <Card className="card-hover">
        <CardContent className="p-6 space-y-4">
          {step === 0 && (
            <>
              <div><Label>Tool Name *</Label><Input value={form.name} onChange={(e) => update("name", e.target.value)} placeholder="e.g. get_weather" className="mt-1" /></div>
              <div><Label>Description</Label><textarea value={form.description} onChange={(e) => update("description", e.target.value)} placeholder="What does this tool do?" className="mt-1 flex min-h-[60px] w-full rounded-lg border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring" /></div>
              <div><Label>Purpose</Label><textarea value={form.purpose} onChange={(e) => update("purpose", e.target.value)} placeholder="When and why to use this tool" className="mt-1 flex min-h-[60px] w-full rounded-lg border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring" /></div>
            </>
          )}
          {step === 1 && (
            <>
              <div><Label>Endpoint URL *</Label><Input value={form.endpoint_url} onChange={(e) => update("endpoint_url", e.target.value)} placeholder="https://api.example.com/v1/endpoint" className="mt-1" /></div>
              <div className="grid grid-cols-2 gap-4">
                <div><Label>HTTP Method</Label><select value={form.http_method} onChange={(e) => update("http_method", e.target.value)} className="mt-1 flex h-9 w-full rounded-lg border border-input bg-transparent px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring">{["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m}>{m}</option>)}</select></div>
                <div><Label>Auth Type</Label><select value={form.auth_type} onChange={(e) => update("auth_type", e.target.value)} className="mt-1 flex h-9 w-full rounded-lg border border-input bg-transparent px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring">{["none", "api_key", "bearer", "basic"].map((a) => <option key={a}>{a}</option>)}</select></div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div><Label>Category</Label><Input value={form.category} onChange={(e) => update("category", e.target.value)} placeholder="general" className="mt-1" /></div>
                <div><Label>Risk Level</Label><select value={form.risk_level} onChange={(e) => update("risk_level", e.target.value)} className="mt-1 flex h-9 w-full rounded-lg border border-input bg-transparent px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring">{["low", "medium", "high"].map((r) => <option key={r}>{r}</option>)}</select></div>
              </div>
            </>
          )}
          {step === 2 && (
            <>
              <div><Label>Input Schema (JSON)</Label><textarea value={form.input_schema} onChange={(e) => update("input_schema", e.target.value)} placeholder='{"type":"object","properties":{}}' className="mt-1 flex min-h-[120px] w-full rounded-lg border border-input bg-transparent px-3 py-2 text-sm font-mono placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring" /></div>
              <div><Label>Output Schema (JSON)</Label><textarea value={form.output_schema} onChange={(e) => update("output_schema", e.target.value)} placeholder='{"type":"object","properties":{}}' className="mt-1 flex min-h-[120px] w-full rounded-lg border border-input bg-transparent px-3 py-2 text-sm font-mono placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring" /></div>
            </>
          )}
          {step === 3 && (
            <div className="space-y-3">
              <p className="text-sm font-medium mb-3">Review your tool configuration</p>
              {[{ label: "Name", value: form.name }, { label: "Endpoint", value: form.endpoint_url, code: true }, { label: "Method", value: form.http_method, badge: true }, { label: "Category", value: form.category }, { label: "Risk", value: form.risk_level, badge: true }, { label: "Enabled", value: form.enabled ? "Yes" : "No", badge: true }].map((d) => (
                <div key={d.label} className="flex items-center justify-between p-2.5 rounded-lg bg-muted/30 text-sm"><span className="text-muted-foreground">{d.label}</span>{d.badge ? <Badge variant="outline">{d.value}</Badge> : d.code ? <code className="text-xs bg-muted px-1.5 py-0.5 rounded max-w-[200px] truncate">{d.value || "(not set)"}</code> : <span className="font-medium">{d.value || "(not set)"}</span>}</div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex justify-between">
        <Button variant="outline" onClick={() => step > 0 ? setStep(step - 1) : navigate("/tools")} disabled={step === 0 && (createTool.isPending || updateTool.isPending)}>{step > 0 ? "Previous" : "Cancel"}</Button>
        {step < 3 ? <Button onClick={() => setStep(step + 1)}><ArrowRight size={14} /> Next</Button> : <Button onClick={handleSubmit} disabled={createTool.isPending || updateTool.isPending}>{createTool.isPending || updateTool.isPending ? <Loader2 size={14} className="animate-spin" /> : null}{isEdit ? "Update Tool" : "Create Tool"}</Button>}
      </div>
    </div>
  )
}
