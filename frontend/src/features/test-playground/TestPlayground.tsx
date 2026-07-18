import { useState, useMemo, useCallback } from "react"
import { useTools, useTestTool } from "@/hooks/use-tools"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Loader2, Play, Copy, Download, Save, Terminal } from "lucide-react"
import { copyToClipboard, downloadJson, generateCurlCommand, formatDuration } from "@/lib/utils"
import type { ToolDefinition } from "@/types/tool"

function DynamicForm({ schema, values, onChange }: {
  schema: Record<string, unknown>
  values: Record<string, unknown>
  onChange: (values: Record<string, unknown>) => void
}) {
  const props = (schema.properties as Record<string, unknown>) || {}

  const updateField = (key: string, value: unknown) => {
    onChange({ ...values, [key]: value })
  }

  return (
    <div className="space-y-3">
      {Object.entries(props).map(([key, prop]) => {
        const p = prop as Record<string, unknown>
        const type = (p.type as string) || "string"
        const required = ((schema.required as string[]) || []).includes(key)
        return (
          <div key={key}>
            <Label className={required ? "after:content-['*'] after:text-destructive after:ml-0.5" : ""}>
              {key}
              {p.description && <span className="text-xs text-muted-foreground ml-2">({p.description as string})</span>}
            </Label>
            {type === "boolean" ? (
              <input
                type="checkbox"
                checked={!!values[key]}
                onChange={(e) => updateField(key, e.target.checked)}
                className="mt-1 rounded border-gray-300"
              />
            ) : type === "number" || type === "integer" ? (
              <Input
                type="number"
                value={values[key] as string || ""}
                onChange={(e) => updateField(key, e.target.value ? Number(e.target.value) : "")}
              />
            ) : type === "object" ? (
              <textarea
                className="w-full h-20 rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono mt-1"
                value={values[key] ? JSON.stringify(values[key], null, 2) : ""}
                onChange={(e) => {
                  try { updateField(key, JSON.parse(e.target.value)) } catch { updateField(key, e.target.value) }
                }}
              />
            ) : (
              <Input
                value={values[key] as string || ""}
                onChange={(e) => updateField(key, e.target.value)}
                placeholder={(p.default as string) || ""}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function TestPlayground() {
  const { data: toolsData, isLoading } = useTools({ enabled: true, pageSize: 100 })
  const testTool = useTestTool()
  const [selectedToolId, setSelectedToolId] = useState<string>("")
  const [inputs, setInputs] = useState<Record<string, unknown>>({})
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState("json")
  const [thought, setThought] = useState("")

  const selectedTool = useMemo(() => {
    return toolsData?.items.find((t: ToolDefinition) => t.id === selectedToolId) || null
  }, [toolsData, selectedToolId])

  const handleToolChange = useCallback((toolId: string) => {
    setSelectedToolId(toolId)
    setInputs({})
    setResult(null)
    setError(null)
    const tool = toolsData?.items.find((t: ToolDefinition) => t.id === toolId)
    if (tool?.input_schema) {
      const defaults: Record<string, unknown> = {}
      const props = (tool.input_schema.properties as Record<string, unknown>) || {}
      for (const [key, prop] of Object.entries(props)) {
        const p = prop as Record<string, unknown>
        if (p.default !== undefined) defaults[key] = p.default
      }
      setInputs(defaults)
    }
  }, [toolsData])

  const handleRunTest = useCallback(async () => {
    if (!selectedToolId) return
    setResult(null)
    setError(null)
    try {
      const res = await testTool.mutateAsync({ toolId: selectedToolId, inputs, dryRun: false })
      setResult(res as unknown as Record<string, unknown>)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error")
    }
  }, [selectedToolId, inputs, testTool])

  const curlCommand = useMemo(() => {
    if (!selectedTool) return ""
    const headers: Record<string, string> = { "Content-Type": "application/json" }
    if (selectedTool.auth_type !== "none") {
      headers["Authorization"] = `Bearer {${selectedTool.auth_ref}}`
    }
    return generateCurlCommand(selectedTool.http_method, selectedTool.endpoint_url, headers, inputs)
  }, [selectedTool, inputs])

  const statusCode = result?.http_status as number | undefined
  const statusBadge = statusCode
    ? statusCode < 300 ? "success" : statusCode < 500 ? "warning" : "destructive"
    : "default"

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Tool Testing Playground</h1>
          <p className="text-muted-foreground">Test your registered HTTP API and MCP tools</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Tool selector + form */}
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Select Tool</CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="flex items-center gap-2 text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading tools...</div>
              ) : (
                <Select
                  value={selectedToolId}
                  onChange={(e) => handleToolChange(e.target.value)}
                  options={(toolsData?.items || []).map((t: ToolDefinition) => ({
                    value: t.id,
                    label: `${t.name} (${t.http_method} ${t.endpoint_url})`,
                  }))}
                  placeholder="Choose a tool to test..."
                />
              )}
            </CardContent>
          </Card>

          {selectedTool && (
            <>
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    Input Parameters
                    <Badge variant={statusBadge}>{selectedTool.http_method}</Badge>
                    <span className="text-sm font-mono text-muted-foreground truncate">{selectedTool.endpoint_url}</span>
                  </CardTitle>
                  <CardDescription>Fill in the parameters defined by the tool's input schema</CardDescription>
                </CardHeader>
                <CardContent>
                  {selectedTool.input_schema && Object.keys(selectedTool.input_schema).length > 0 ? (
                    <DynamicForm
                      schema={selectedTool.input_schema as Record<string, unknown>}
                      values={inputs}
                      onChange={setInputs}
                    />
                  ) : (
                    <p className="text-sm text-muted-foreground">This tool accepts no input parameters</p>
                  )}
                </CardContent>
              </Card>

              {/* T→A→O Visualization */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Terminal className="h-4 w-4" />
                    Thought → Action → Observation
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div>
                    <Label>Thought (agent reasoning)</Label>
                    <textarea
                      className="w-full h-20 rounded-md border border-input bg-muted/50 px-3 py-2 text-sm mt-1"
                      value={thought}
                      onChange={(e) => setThought(e.target.value)}
                      placeholder="e.g., The user wants to search for products. I should use the search tool with their query."
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <Label>Action</Label>
                      <div className="mt-1 p-3 rounded-md border bg-muted/30">
                        <div className="text-sm font-medium">{selectedTool.name}</div>
                        <div className="text-xs font-mono text-muted-foreground mt-1">
                          {JSON.stringify(inputs, null, 2)}
                        </div>
                      </div>
                    </div>
                    <div>
                      <Label>Observation</Label>
                      <div className="mt-1 p-3 rounded-md border bg-muted/30 min-h-[80px]">
                        {result ? (
                          <pre className="text-xs font-mono whitespace-pre-wrap">{JSON.stringify(result, null, 2)}</pre>
                        ) : (
                          <span className="text-xs text-muted-foreground">Run test to see observation</span>
                        )}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </div>

        {/* Right: Results panel */}
        <div className="space-y-4">
          <div className="flex gap-2">
            <Button
              className="flex-1"
              onClick={handleRunTest}
              disabled={!selectedToolId || testTool.isPending}
            >
              {testTool.isPending ? (
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
              ) : (
                <Play className="h-4 w-4 mr-1" />
              )}
              Run Test
            </Button>
            <Button variant="outline" size="icon" onClick={() => copyToClipboard(curlCommand)} title="Copy cURL">
              <Copy className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="icon" onClick={() => {
              if (result) downloadJson(result, `${selectedTool?.name || "tool"}-result.json`)
            }} disabled={!result} title="Export JSON">
              <Download className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="icon" title="Save as Example" disabled>
              <Save className="h-4 w-4" />
            </Button>
          </div>

          {error && (
            <Card className="border-destructive">
              <CardContent className="pt-4">
                <Badge variant="destructive">Error</Badge>
                <pre className="mt-2 text-sm font-mono text-destructive whitespace-pre-wrap">{error}</pre>
              </CardContent>
            </Card>
          )}

          {result && (
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm">Response</CardTitle>
                  <div className="flex items-center gap-2">
                    <Badge variant={statusBadge as any}>{statusCode || "—"}</Badge>
                    <span className="text-xs text-muted-foreground">{formatDuration((result.duration_ms as number) || 0)}</span>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <Tabs value={activeTab} onValueChange={setActiveTab}>
                  <TabsList>
                    <TabsTrigger value="json">JSON</TabsTrigger>
                    <TabsTrigger value="raw">Raw</TabsTrigger>
                    <TabsTrigger value="headers">Headers</TabsTrigger>
                  </TabsList>
                  <TabsContent value="json">
                    <ScrollArea className="h-64">
                      <pre className="text-xs font-mono">{JSON.stringify(result.data || result, null, 2)}</pre>
                    </ScrollArea>
                  </TabsContent>
                  <TabsContent value="raw">
                    <ScrollArea className="h-64">
                      <pre className="text-xs font-mono">{(result.raw_response_excerpt as string) || "No raw response"}</pre>
                    </ScrollArea>
                  </TabsContent>
                  <TabsContent value="headers">
                    <ScrollArea className="h-64">
                      {result.response_headers ? (
                        <table className="text-xs w-full">
                          <tbody>
                            {Object.entries(result.response_headers as Record<string, string>).map(([k, v]) => (
                              <tr key={k} className="border-b">
                                <td className="font-mono pr-4 py-1 text-muted-foreground">{k}</td>
                                <td className="font-mono py-1">{v}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : (
                        <span className="text-muted-foreground">No headers captured</span>
                      )}
                    </ScrollArea>
                  </TabsContent>
                </Tabs>
              </CardContent>
            </Card>
          )}

          {/* Request preview */}
          {selectedTool && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">cURL Command</CardTitle>
              </CardHeader>
              <CardContent>
                <ScrollArea className="h-32">
                  <pre className="text-xs font-mono whitespace-pre-wrap">{curlCommand}</pre>
                </ScrollArea>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
