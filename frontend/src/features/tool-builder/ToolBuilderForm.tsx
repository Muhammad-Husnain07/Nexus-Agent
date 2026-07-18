import { useState, useCallback } from "react"
import { useForm, Controller } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { ScrollArea } from "@/components/ui/scroll-area"
import JsonSchemaEditor from "@/features/tool-builder/JsonSchemaEditor"
import { useCreateTool, useUpdateTool, useTool } from "@/hooks/use-tools"
import { Check, ChevronLeft, ChevronRight, Eye, Send, Loader2 } from "lucide-react"
import type { ToolCreatePayload } from "@/types/tool"

const steps = [
  "Basic Info",
  "API Configuration",
  "Authentication",
  "Input Schema",
  "Output Schema",
  "Examples & Testing",
  "Risk & Approval",
]

const toolSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().optional().default(""),
  purpose: z.string().optional().default(""),
  tool_type: z.enum(["http_api", "mcp"]).default("http_api"),
  endpoint_url: z.string().optional().default(""),
  mcp_server_url: z.string().optional().default(""),
  http_method: z.string().default("GET"),
  auth_type: z.string().default("none"),
  auth_ref: z.string().optional().default(""),
  input_schema: z.any().optional(),
  output_schema: z.any().optional(),
  validation_rules: z.any().optional(),
  category: z.string().optional().default("general"),
  tags: z.string().optional().default(""),
  requires_approval: z.boolean().default(false),
  risk_level: z.string().default("low"),
  rate_limit_per_minute: z.number().nullable().optional().default(null),
  idempotent: z.boolean().default(false),
})

type ToolFormData = z.infer<typeof toolSchema>

const HTTP_METHODS = [
  { value: "GET", label: "GET", color: "text-green-600 bg-green-50 border-green-200" },
  { value: "POST", label: "POST", color: "text-blue-600 bg-blue-50 border-blue-200" },
  { value: "PUT", label: "PUT", color: "text-orange-600 bg-orange-50 border-orange-200" },
  { value: "PATCH", label: "PATCH", color: "text-amber-600 bg-amber-50 border-amber-200" },
  { value: "DELETE", label: "DELETE", color: "text-red-600 bg-red-50 border-red-200" },
]

const AUTH_TYPES = [
  { value: "none", label: "No Auth" },
  { value: "bearer", label: "Bearer Token" },
  { value: "basic", label: "Basic Auth" },
  { value: "api_key", label: "API Key" },
  { value: "oauth2", label: "OAuth 2.0" },
]

const RISK_LEVELS = [
  { value: "low", label: "Low", color: "bg-green-100 text-green-800" },
  { value: "medium", label: "Medium", color: "bg-yellow-100 text-yellow-800" },
  { value: "high", label: "High", color: "bg-red-100 text-red-800" },
]

const CATEGORIES = ["general", "data", "analytics", "communication", "automation", "ai", "security", "devops"]

export default function ToolBuilderForm() {
  const { id } = useParams()
  const isEditing = !!id
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [urlValidating, setUrlValidating] = useState(false)
  const [urlStatus, setUrlStatus] = useState<"idle" | "reachable" | "unreachable">("idle")

  const { data: existingTool } = useTool(isEditing ? id : undefined)
  const createTool = useCreateTool()
  const updateTool = useUpdateTool()

  const form = useForm<ToolFormData>({
    resolver: zodResolver(toolSchema),
    defaultValues: {
      name: existingTool?.name || "",
      description: existingTool?.description || "",
      purpose: existingTool?.purpose || "",
      tool_type: (existingTool?.tool_type as "http_api" | "mcp") || "http_api",
      endpoint_url: existingTool?.endpoint_url || "",
      mcp_server_url: existingTool?.mcp_server_url || "",
      http_method: existingTool?.http_method || "GET",
      auth_type: existingTool?.auth_type || "none",
      auth_ref: existingTool?.auth_ref || "",
      category: existingTool?.category || "general",
      tags: (existingTool?.tags || []).join(", "),
      requires_approval: existingTool?.requires_approval || false,
      risk_level: existingTool?.risk_level || "low",
      rate_limit_per_minute: existingTool?.rate_limit_per_minute ?? null,
      idempotent: existingTool?.idempotent || false,
    },
  })

  const watchToolType = form.watch("tool_type")
  const watchEndpointUrl = form.watch("endpoint_url")
  const watchHttpMethod = form.watch("http_method")
  const watchAuthType = form.watch("auth_type")
  const formValues = form.watch()

  const validateUrl = useCallback(async (url: string) => {
    if (!url || watchToolType !== "http_api") return
    setUrlValidating(true)
    setUrlStatus("idle")
    try {
      const resp = await fetch(url, { method: "HEAD", mode: "no-cors" })
      setUrlStatus(resp.type === "opaque" ? "reachable" : resp.ok ? "reachable" : "unreachable")
    } catch {
      setUrlStatus("unreachable")
    } finally {
      setUrlValidating(false)
    }
  }, [watchToolType])

  const getHttpMethodColor = (method: string) => {
    const m = HTTP_METHODS.find((h) => h.value === method)
    return m?.color || ""
  }

  async function onSubmit() {
    const valid = await form.trigger()
    if (!valid) return

    const raw = form.getValues()
    const payload: ToolCreatePayload = {
      name: raw.name,
      description: raw.description || "",
      purpose: raw.purpose || "",
      tool_type: raw.tool_type,
      endpoint_url: raw.tool_type === "http_api" ? raw.endpoint_url : "",
      mcp_server_url: raw.tool_type === "mcp" ? raw.mcp_server_url : "",
      http_method: raw.http_method,
      auth_type: raw.auth_type,
      auth_ref: raw.auth_ref || "",
      category: raw.category || "general",
      tags: raw.tags ? raw.tags.split(",").map((t: string) => t.trim()).filter(Boolean) : [],
      requires_approval: raw.requires_approval,
      risk_level: raw.risk_level,
      rate_limit_per_minute: raw.rate_limit_per_minute,
      idempotent: raw.idempotent,
    }

    try {
      if (isEditing && id) {
        await updateTool.mutateAsync({ id, ...payload })
      } else {
        await createTool.mutateAsync(payload)
      }
      navigate("/")
    } catch {
      // Error toast handled by mutation
    }
  }

  const nextStep = async () => {
    const fields = getStepFields(step)
    const valid = await form.trigger(fields as any)
    if (valid && step < steps.length - 1) setStep(step + 1)
  }

  function getStepFields(s: number) {
    switch (s) {
      case 0: return ["name", "description", "purpose", "category", "tags"]
      case 1: return ["tool_type", "endpoint_url", "mcp_server_url", "http_method"]
      case 2: return ["auth_type", "auth_ref"]
      case 6: return ["requires_approval", "risk_level", "rate_limit_per_minute"]
      default: return []
    }
  }

  const previewPayload: ToolCreatePayload = {
    name: formValues.name,
    description: formValues.description,
    purpose: formValues.purpose,
    tool_type: formValues.tool_type,
    endpoint_url: formValues.endpoint_url,
    mcp_server_url: formValues.mcp_server_url,
    http_method: formValues.http_method,
    auth_type: formValues.auth_type,
    auth_ref: formValues.auth_ref,
    category: formValues.category,
    tags: formValues.tags ? formValues.tags.split(",").map(t => t.trim()).filter(Boolean) : [],
    requires_approval: formValues.requires_approval,
    risk_level: formValues.risk_level,
    rate_limit_per_minute: formValues.rate_limit_per_minute,
    idempotent: formValues.idempotent,
  }

  return (
    <div className="flex h-screen">
      {/* Main content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl mx-auto">
          <h1 className="text-2xl font-bold mb-2">{isEditing ? "Edit Tool" : "Create New Tool"}</h1>
          <p className="text-muted-foreground mb-6">HTTP API connections and MCP servers ONLY — no custom Python code execution</p>

          {/* Step indicator */}
          <div className="flex items-center gap-1 mb-8 overflow-x-auto pb-2">
            {steps.map((s, i) => (
              <div key={i} className="flex items-center gap-1 shrink-0">
                <button
                  onClick={() => i <= step && setStep(i)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm transition-colors
                    ${i === step ? "bg-primary text-primary-foreground" : ""}
                    ${i < step ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100" : ""}
                    ${i > step ? "text-muted-foreground" : ""}
                  `}
                >
                  {i < step ? <Check className="h-3 w-3" /> : <span className="text-xs">{i + 1}</span>}
                  <span className="hidden sm:inline">{s}</span>
                </button>
                {i < steps.length - 1 && <div className="w-6 h-px bg-border" />}
              </div>
            ))}
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{steps[step]}</CardTitle>
              <CardDescription>Step {step + 1} of {steps.length}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Step 0: Basic Info */}
              {step === 0 && (
                <>
                  <div>
                    <Label>Name *</Label>
                    <Input {...form.register("name")} placeholder="my-api-tool" />
                    {form.formState.errors.name && <p className="text-sm text-destructive mt-1">{form.formState.errors.name.message}</p>}
                  </div>
                  <div>
                    <Label>Description</Label>
                    <Textarea {...form.register("description")} placeholder="What does this tool do?" rows={3} />
                  </div>
                  <div>
                    <Label>Purpose</Label>
                    <Textarea {...form.register("purpose")} placeholder="When should the agent use this tool?" rows={2} />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <Label>Category</Label>
                      <Select {...form.register("category")} options={CATEGORIES.map(c => ({ value: c, label: c.charAt(0).toUpperCase() + c.slice(1) }))} />
                    </div>
                    <div>
                      <Label>Tags (comma-separated)</Label>
                      <Input {...form.register("tags")} placeholder="search, api, data" />
                    </div>
                  </div>
                </>
              )}

              {/* Step 1: API Configuration */}
              {step === 1 && (
                <>
                  <div>
                    <Label>Tool Type</Label>
                    <div className="flex gap-4 mt-1">
                      <label className={`flex-1 border rounded-lg p-4 cursor-pointer transition-colors ${watchToolType === "http_api" ? "border-primary bg-primary/5" : "hover:border-muted-foreground"}`}>
                        <input type="radio" {...form.register("tool_type")} value="http_api" className="sr-only" />
                        <div className="font-medium">HTTP API</div>
                        <div className="text-sm text-muted-foreground">Standard REST API endpoint</div>
                      </label>
                      <label className={`flex-1 border rounded-lg p-4 cursor-pointer transition-colors ${watchToolType === "mcp" ? "border-primary bg-primary/5" : "hover:border-muted-foreground"}`}>
                        <input type="radio" {...form.register("tool_type")} value="mcp" className="sr-only" />
                        <div className="font-medium">MCP Server</div>
                        <div className="text-sm text-muted-foreground">Model Context Protocol server</div>
                      </label>
                    </div>
                  </div>

                  {watchToolType === "http_api" && (
                    <>
                      <div>
                        <Label>Endpoint URL *</Label>
                        <div className="flex gap-2">
                          <Input {...form.register("endpoint_url")} placeholder="https://api.example.com/v1/action" className="flex-1" />
                          <Button variant="outline" size="sm" onClick={() => validateUrl(watchEndpointUrl)} disabled={urlValidating}>
                            {urlValidating ? <Loader2 className="h-4 w-4 animate-spin" /> : "Test"}
                          </Button>
                        </div>
                        {urlStatus === "reachable" && <p className="text-sm text-green-600 mt-1">Endpoint is reachable</p>}
                        {urlStatus === "unreachable" && <p className="text-sm text-amber-600 mt-1">Endpoint unreachable — check URL or CORS</p>}
                      </div>
                      <div>
                        <Label>HTTP Method</Label>
                        <div className="flex gap-2 mt-1">
                          {HTTP_METHODS.map((m) => (
                            <label key={m.value} className={`flex-1 border rounded-md p-2 text-center text-sm font-mono cursor-pointer transition-colors
                              ${watchHttpMethod === m.value ? `${m.color} border-current` : "hover:bg-muted"}
                            `}>
                              <input type="radio" {...form.register("http_method")} value={m.value} className="sr-only" />
                              {m.value}
                            </label>
                          ))}
                        </div>
                      </div>
                    </>
                  )}

                  {watchToolType === "mcp" && (
                    <div>
                      <Label>MCP Server URL *</Label>
                      <Input {...form.register("mcp_server_url")} placeholder="https://mcp.example.com" />
                    </div>
                  )}
                </>
              )}

              {/* Step 2: Authentication */}
              {step === 2 && (
                <>
                  <div>
                    <Label>Authentication Type</Label>
                    <Select {...form.register("auth_type")} options={AUTH_TYPES} />
                  </div>
                  {watchAuthType !== "none" && (
                    <div>
                      <Label>Auth Reference</Label>
                      <div className="flex gap-2">
                        <Input {...form.register("auth_ref")} placeholder="vault://my-secret-key" className="flex-1" />
                        <Button variant="outline" size="sm">Pick Secret</Button>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">
                        Reference a stored secret from the vault. Format: vault://secret-name
                      </p>
                    </div>
                  )}
                </>
              )}

              {/* Step 3: Input Schema */}
              {step === 3 && (
                <div>
                  <Label className="mb-2 block">Input Schema (JSON Schema Draft 7)</Label>
                  <JsonSchemaEditor
                    value={form.getValues("input_schema") as Record<string, unknown>}
                    onChange={(schema) => form.setValue("input_schema", schema)}
                    title={`${form.watch("name") || "tool"}-input`}
                  />
                </div>
              )}

              {/* Step 4: Output Schema */}
              {step === 4 && (
                <div>
                  <Label className="mb-2 block">Output Schema (JSON Schema Draft 7)</Label>
                  <JsonSchemaEditor
                    value={form.getValues("output_schema") as Record<string, unknown>}
                    onChange={(schema) => form.setValue("output_schema", schema)}
                    title={`${form.watch("name") || "tool"}-output`}
                  />
                </div>
              )}

              {/* Step 5: Examples & Testing */}
              {step === 5 && (
                <p className="text-muted-foreground text-sm">
                  Example invocations will be added in the testing playground after the tool is created.
                  <br />
                  <Button variant="link" className="p-0 h-auto" onClick={() => navigate("/test")}>
                    Go to Test Playground
                  </Button>
                </p>
              )}

              {/* Step 6: Risk & Approval */}
              {step === 6 && (
                <>
                  <div className="flex items-center justify-between">
                    <div>
                      <Label>Requires Approval</Label>
                      <p className="text-sm text-muted-foreground">Human-in-the-loop approval for each execution</p>
                    </div>
                    <Controller name="requires_approval" control={form.control} render={({ field }) => (
                      <Switch checked={field.value} onCheckedChange={field.onChange} />
                    )} />
                  </div>
                  <Separator />
                  <div>
                    <Label>Risk Level</Label>
                    <div className="flex gap-2 mt-1">
                      {RISK_LEVELS.map((r) => (
                        <label key={r.value} className={`flex-1 border rounded-md p-3 text-center cursor-pointer transition-colors
                          ${form.watch("risk_level") === r.value ? `${r.color} border-current` : "hover:bg-muted"}
                        `}>
                          <input type="radio" {...form.register("risk_level")} value={r.value} className="sr-only" />
                          <span className="text-sm font-medium">{r.label}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                  <Separator />
                  <div>
                    <Label>Rate Limit (requests/minute)</Label>
                    <Input type="number" {...form.register("rate_limit_per_minute", { valueAsNumber: true })} placeholder="Unlimited" />
                  </div>
                  <Separator />
                  <div className="flex items-center justify-between">
                    <div>
                      <Label>Idempotent</Label>
                      <p className="text-sm text-muted-foreground">Safe to retry — tool supports idempotent execution</p>
                    </div>
                    <Controller name="idempotent" control={form.control} render={({ field }) => (
                      <Switch checked={field.value} onCheckedChange={field.onChange} />
                    )} />
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          {/* Navigation */}
          <div className="flex items-center justify-between mt-6">
            <Button variant="outline" onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}>
              <ChevronLeft className="h-4 w-4 mr-1" /> Previous
            </Button>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setPreviewOpen(!previewOpen)}>
                <Eye className="h-4 w-4 mr-1" /> Preview
              </Button>
              {step < steps.length - 1 ? (
                <Button onClick={nextStep}>
                  Next <ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              ) : (
                <Button onClick={onSubmit} disabled={createTool.isPending || updateTool.isPending}>
                  {(createTool.isPending || updateTool.isPending) ? (
                    <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  ) : (
                    <Send className="h-4 w-4 mr-1" />
                  )}
                  {isEditing ? "Update Tool" : "Create Tool"}
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Preview panel */}
      {previewOpen && (
        <div className="w-96 border-l bg-muted/30 p-4 overflow-y-auto">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold">Tool Definition Preview</h3>
            <Button variant="ghost" size="sm" onClick={() => setPreviewOpen(false)}>Close</Button>
          </div>
          <ScrollArea className="h-[calc(100vh-8rem)]">
            <pre className="text-xs font-mono whitespace-pre-wrap">
              {JSON.stringify(previewPayload, null, 2)}
            </pre>
          </ScrollArea>
        </div>
      )}
    </div>
  )
}
