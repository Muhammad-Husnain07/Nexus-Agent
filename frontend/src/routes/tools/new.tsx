import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { ArrowLeft, Loader2, Plus, Trash2 } from "lucide-react"
import { useCreateTool } from "@/hooks/use-tools-api"
import { toast } from "sonner"
import { cn } from "@/lib/utils"

const steps = ["Basic Info", "API Config", "Input Schema", "Risk & Approval"]

export default function ToolNewPage() {
  const navigate = useNavigate()
  const createTool = useCreateTool()
  const [step, setStep] = useState(0)
  const [form, setForm] = useState({
    name: "", description: "", purpose: "",
    endpoint_url: "", http_method: "GET", auth_type: "none",
    input_schema: "", output_schema: "",
    tags: "", category: "general",
    requires_approval: false, risk_level: "low", enabled: true,
  })

  const update = (field: string, value: string | boolean) => setForm((f) => ({ ...f, [field]: value }))

  const handleSubmit = () => {
    if (!form.name.trim()) { toast.error("Tool name is required"); return }
    if (!form.endpoint_url.trim()) { toast.error("Endpoint URL is required"); return }

    let inputSchema = {}
    let outputSchema = {}
    try { if (form.input_schema.trim()) inputSchema = JSON.parse(form.input_schema) } catch { toast.error("Invalid Input Schema JSON"); return }
    try { if (form.output_schema.trim()) outputSchema = JSON.parse(form.output_schema) } catch { toast.error("Invalid Output Schema JSON"); return }

    const payload = {
      name: form.name.trim(),
      description: form.description.trim(),
      purpose: form.purpose.trim(),
      endpoint_url: form.endpoint_url.trim(),
      http_method: form.http_method,
      auth_type: form.auth_type,
      input_schema: inputSchema,
      output_schema: outputSchema,
      tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
      category: form.category,
      requires_approval: form.requires_approval,
      risk_level: form.risk_level,
      enabled: form.enabled,
    }

    createTool.mutate(payload, {
      onSuccess: () => { toast.success("Tool created"); navigate("/tools") },
      onError: () => toast.error("Failed to create tool"),
    })
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => navigate("/tools")}><ArrowLeft size={18} /></Button>
        <div>
          <h1 className="text-xl font-bold">Create Tool</h1>
          <p className="text-xs text-muted-foreground">Register a new tool capability</p>
        </div>
      </div>

      <div className="flex gap-2">
        {steps.map((s, i) => (
          <div key={s} className={cn("flex-1 h-1.5 rounded-full transition-colors", i <= step ? "bg-primary" : "bg-muted")} />
        ))}
      </div>
      <div className="flex gap-2 text-xs text-muted-foreground">
        {steps.map((s, i) => (
          <span key={s} className={cn("flex-1", i === step && "text-primary font-medium")}>{s}</span>
        ))}
      </div>

      <Card>
        <CardHeader><CardTitle>{steps[step]}</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          {step === 0 && (
            <>
              <div>
                <label className="text-sm font-medium mb-1 block">Tool Name *</label>
                <Input value={form.name} onChange={(e) => update("name", e.target.value)} placeholder="e.g. get_weather" />
              </div>
              <div>
                <label className="text-sm font-medium mb-1 block">Description</label>
                <textarea value={form.description} onChange={(e) => update("description", e.target.value)}
                  className="flex min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  placeholder="What does this tool do?" />
              </div>
              <div>
                <label className="text-sm font-medium mb-1 block">Purpose</label>
                <textarea value={form.purpose} onChange={(e) => update("purpose", e.target.value)}
                  className="flex min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  placeholder="When should the agent use this tool?" />
              </div>
              <div>
                <label className="text-sm font-medium mb-1 block">Tags (comma-separated)</label>
                <Input value={form.tags} onChange={(e) => update("tags", e.target.value)} placeholder="e.g. weather, data, api" />
              </div>
              <div>
                <label className="text-sm font-medium mb-1 block">Category</label>
                <select value={form.category} onChange={(e) => update("category", e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  {["general", "data", "communication", "content", "analytics", "automation", "ai", "development"].map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
            </>
          )}

          {step === 1 && (
            <>
              <div>
                <label className="text-sm font-medium mb-1 block">Endpoint URL *</label>
                <Input value={form.endpoint_url} onChange={(e) => update("endpoint_url", e.target.value)} placeholder="https://api.example.com/v1/weather" />
              </div>
              <div>
                <label className="text-sm font-medium mb-1 block">HTTP Method</label>
                <select value={form.http_method} onChange={(e) => update("http_method", e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => (<option key={m} value={m}>{m}</option>))}
                </select>
              </div>
              <div>
                <label className="text-sm font-medium mb-1 block">Auth Type</label>
                <select value={form.auth_type} onChange={(e) => update("auth_type", e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <option value="none">None</option>
                  <option value="bearer">Bearer Token</option>
                  <option value="basic">Basic Auth</option>
                  <option value="api_key">API Key</option>
                </select>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <div>
                <label className="text-sm font-medium mb-1 block">Input Schema (JSON)</label>
                <textarea value={form.input_schema} onChange={(e) => update("input_schema", e.target.value)}
                  className="flex min-h-[150px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  placeholder='{"type":"object","properties":{"location":{"type":"string"}},"required":["location"]}' />
              </div>
              <div>
                <label className="text-sm font-medium mb-1 block">Output Schema (JSON)</label>
                <textarea value={form.output_schema} onChange={(e) => update("output_schema", e.target.value)}
                  className="flex min-h-[150px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  placeholder='{"type":"object","properties":{"temperature":{"type":"number"}}}' />
              </div>
            </>
          )}

          {step === 3 && (
            <>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="approval" checked={form.requires_approval} onChange={(e) => update("requires_approval", e.target.checked)}
                  className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary" />
                <label htmlFor="approval" className="text-sm font-medium">Requires human approval</label>
              </div>
              <div>
                <label className="text-sm font-medium mb-1 block">Risk Level</label>
                <select value={form.risk_level} onChange={(e) => update("risk_level", e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="enabled" checked={form.enabled} onChange={(e) => update("enabled", e.target.checked)}
                  className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary" />
                <label htmlFor="enabled" className="text-sm font-medium">Enabled</label>
              </div>
              <div className="pt-4 border-t">
                <h3 className="text-sm font-medium mb-2">Summary</h3>
                <div className="space-y-1 text-sm text-muted-foreground">
                  <p>Name: <span className="text-foreground">{form.name || "-"}</span></p>
                  <p>Endpoint: <span className="text-foreground">{form.endpoint_url || "-"}</span></p>
                  <p>Method: <Badge variant="outline">{form.http_method}</Badge></p>
                  <p>Risk: <Badge variant={form.risk_level === "low" ? "success" : form.risk_level === "medium" ? "warning" : "destructive"}>{form.risk_level}</Badge></p>
                  <p>Approval: {form.requires_approval ? <Badge variant="warning">Required</Badge> : <Badge variant="success">None</Badge>}</p>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <div className="flex justify-between">
        <Button variant="outline" onClick={() => step === 0 ? navigate("/tools") : setStep(step - 1)} disabled={createTool.isPending}>
          {step === 0 ? "Cancel" : "Back"}
        </Button>
        {step < steps.length - 1 ? (
          <Button onClick={() => setStep(step + 1)}>Next</Button>
        ) : (
          <Button onClick={handleSubmit} disabled={createTool.isPending}>
            {createTool.isPending ? <><Loader2 size={16} className="animate-spin" /> Creating...</> : "Create Tool"}
          </Button>
        )}
      </div>
    </div>
  )
}
