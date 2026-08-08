import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import {
  useWorkflowsList,
  useCreateWorkflow,
  useUpdateWorkflow,
  useDeleteWorkflow,
  useToggleWorkflow,
} from "@/hooks/use-workflows-api";
import type { Workflow, WorkflowStep } from "@/types/workflow";
import { Plus, Trash2, Power, PowerOff, ChevronDown, ChevronRight, Pencil, X } from "lucide-react";

/** Step kind ↔ field mapping — the editor keeps exactly one kind active. */
function stepKind(s: WorkflowStep): string {
  if (s.dynamic) return "dynamic";
  if (s.workflow_ref) return "workflow_ref";
  if (s.template) return "template";
  return "intent";
}

function StepEditor({ steps, onChange }: { steps: WorkflowStep[]; onChange: (s: WorkflowStep[]) => void }) {
  const update = (i: number, patch: Partial<WorkflowStep>) => {
    onChange(steps.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  };
  return (
    <div className="space-y-3">
      {steps.map((s, i) => {
        const kind = stepKind(s);
        return (
          <div key={i} className="space-y-2 rounded-md border p-3">
            <div className="flex items-center gap-2">
              <span className="w-8 text-xs text-muted-foreground">#{i + 1}</span>
              <Input
                className="h-8 w-28 text-xs"
                placeholder="step_N"
                value={s.id}
                onChange={(e) => update(i, { id: e.target.value })}
              />
              <Input
                className="h-8 flex-1 text-xs"
                placeholder="Description"
                value={s.description ?? ""}
                onChange={(e) => update(i, { description: e.target.value })}
              />
              <Button size="sm" variant="ghost" onClick={() => onChange(steps.filter((_, idx) => idx !== i))}>
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>

            <div className="flex items-center gap-2">
              <select
                className="h-8 rounded-md border bg-background px-2 text-xs"
                value={kind}
                onChange={(e) => {
                  const next = e.target.value;
                  update(i, {
                    dynamic: next === "dynamic",
                    workflow_ref: next === "workflow_ref" ? (s.workflow_ref ?? "") : undefined,
                    template: next === "template" ? (s.template ?? "") : undefined,
                    intent: next === "intent" ? (s.intent ?? "") : undefined,
                    capability: undefined,
                  });
                }}
              >
                <option value="intent">Capability</option>
                <option value="dynamic">Dynamic (hybrid)</option>
                <option value="workflow_ref">Workflow building block</option>
                <option value="template">Template</option>
              </select>
              <Input
                className="h-8 flex-1 text-xs"
                placeholder={
                  kind === "dynamic" ? "Dynamic step question (optional)"
                    : kind === "workflow_ref" ? "Workflow name to reuse"
                    : kind === "template" ? "Template name"
                    : "Capability name (e.g. get_invoice)"
                }
                value={String(kind === "dynamic" ? "" : s.workflow_ref ?? s.template ?? s.intent ?? "")}
                onChange={(e) => {
                  if (kind === "dynamic") update(i, { question: e.target.value });
                  else if (kind === "workflow_ref") update(i, { workflow_ref: e.target.value });
                  else if (kind === "template") update(i, { template: e.target.value });
                  else update(i, { intent: e.target.value });
                }}
              />
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center gap-2 rounded-md border px-2 py-1.5">
                <Switch
                  checked={s.requires_input ?? false}
                  onCheckedChange={(v) => update(i, { requires_input: v })}
                />
                <span className="text-[10px] text-muted-foreground">Ask user</span>
              </div>
              <Input
                className="h-8 flex-1 text-xs"
                placeholder="Question asked in-chat (requires_input)"
                value={s.question ?? ""}
                onChange={(e) => update(i, { question: e.target.value })}
              />
            </div>
            <Input
              className="h-8 text-xs font-mono"
              placeholder='Inputs JSON (e.g. {"invoice_id": "${invoice_id}"})'
              value={s.inputs ? JSON.stringify(s.inputs) : ""}
              onChange={(e) => {
                const raw = e.target.value.trim();
                if (!raw) { update(i, { inputs: {} }); return; }
                try {
                  update(i, { inputs: JSON.parse(raw) as Record<string, unknown> });
                } catch {
                  /* keep previous value until valid JSON */
                }
              }}
            />
          </div>
        );
      })}
      <Button
        size="sm"
        variant="outline"
        onClick={() => onChange([...steps, { id: `step_${steps.length + 1}`, intent: "" }])}
      >
        <Plus className="h-3 w-3" /> Add step
      </Button>
    </div>
  );
}

export default function WorkflowsPage() {
  const { data, isLoading } = useWorkflowsList();
  const createWorkflow = useCreateWorkflow();
  const updateWorkflow = useUpdateWorkflow();
  const deleteWorkflow = useDeleteWorkflow();
  const toggleWorkflow = useToggleWorkflow();

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [pattern, setPattern] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState(0);
  const [enabled, setEnabled] = useState(true);
  const [steps, setSteps] = useState<WorkflowStep[]>([{ id: "step_1", intent: "" }]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const openCreate = () => {
    setEditingId(null);
    setName("");
    setPattern("");
    setDescription("");
    setPriority(0);
    setEnabled(true);
    setSteps([{ id: "step_1", intent: "" }]);
    setEditorOpen(true);
  };

  const openEdit = (wf: Workflow) => {
    setEditingId(wf.id);
    setName(wf.name);
    setPattern(wf.trigger_intent_pattern);
    setDescription(wf.description);
    setPriority(wf.priority);
    setEnabled(wf.enabled);
    setSteps(wf.steps.map((s) => ({ ...s })));
    setEditorOpen(true);
  };

  const closeEditor = () => {
    setEditorOpen(false);
    setEditingId(null);
  };

  const handleSave = async () => {
    if (!name.trim()) {
      toast.error("Workflow name is required");
      return;
    }
    if (steps.length === 0 || steps.some((s) => !s.id.trim())) {
      toast.error("Each step needs an id");
      return;
    }
    if (new Set(steps.map((s) => s.id)).size !== steps.length) {
      toast.error("Step ids must be unique");
      return;
    }
    const body = {
      name: name.trim(),
      description,
      trigger_intent_pattern: pattern.trim(),
      priority,
      enabled,
      steps,
    };
    try {
      if (editingId) {
        await updateWorkflow.mutateAsync({ id: editingId, data: body });
        toast.success("Workflow updated (version bumped)");
      } else {
        await createWorkflow.mutateAsync(body);
        toast.success("Workflow created");
      }
      closeEditor();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save workflow";
      toast.error(msg);
    }
  };

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Workflows</h1>
          <p className="text-sm text-muted-foreground">
            Deterministic business processes matched against user requests.
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4" /> New Workflow
        </Button>
      </div>

      {editorOpen && (
        <Card className="card-hover">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">
              {editingId ? `Edit workflow — ${name || "…"}` : "Register deterministic workflow"}
            </CardTitle>
            <Button size="sm" variant="ghost" onClick={closeEditor}><X className="h-4 w-4" /></Button>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1"><Label>Name *</Label><Input placeholder="Unique name (e.g. invoice_approval)" value={name} onChange={(e) => setName(e.target.value)} /></div>
              <div className="space-y-1"><Label>Intent pattern</Label><Input placeholder="e.g. approve invoice" value={pattern} onChange={(e) => setPattern(e.target.value)} /></div>
            </div>
            <div className="space-y-1"><Label>Description</Label><Input placeholder="What this workflow does" value={description} onChange={(e) => setDescription(e.target.value)} /></div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1"><Label>Match priority</Label><Input type="number" min={0} value={priority} onChange={(e) => setPriority(Number(e.target.value) || 0)} /></div>
              <div className="flex items-end justify-between rounded-md border bg-muted/30 px-3 py-2">
                <div><Label>Active</Label><p className="text-xs text-muted-foreground">Matched against user requests</p></div>
                <Switch checked={enabled} onCheckedChange={setEnabled} />
              </div>
            </div>
            <StepEditor steps={steps} onChange={setSteps} />
            <div className="flex gap-2">
              <Button onClick={handleSave} disabled={createWorkflow.isPending || updateWorkflow.isPending}>
                {editingId ? "Update Workflow" : "Register"}
              </Button>
              <Button variant="outline" onClick={closeEditor}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6 text-sm text-muted-foreground">Loading workflows…</div>
          ) : (data?.workflows?.length ?? 0) === 0 ? (
            <div className="p-6 text-sm text-muted-foreground">
              No workflows registered. Define deterministic processes for your business flows.
            </div>
          ) : (
            <div className="divide-y">
              {data?.workflows?.map((wf: Workflow) => (
                <div key={wf.id} className="p-4">
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => setExpanded((e) => ({ ...e, [wf.id]: !e[wf.id] }))}
                      className="text-muted-foreground hover:text-foreground"
                    >
                      {expanded[wf.id] ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </button>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{wf.name}</span>
                        <Badge variant={wf.enabled ? "success" : "secondary"}>
                          {wf.enabled ? "Active" : "Inactive"}
                        </Badge>
                        <Badge variant="outline">v{wf.version}</Badge>
                        {wf.priority > 0 && <Badge variant="secondary" className="text-[10px]">p{wf.priority}</Badge>}
                      </div>
                      {wf.description && (
                        <p className="text-xs text-muted-foreground">{wf.description}</p>
                      )}
                      {wf.trigger_intent_pattern && (
                        <p className="mt-0.5 text-xs font-mono text-muted-foreground">
                          pattern: {wf.trigger_intent_pattern} · {wf.steps.length} steps
                        </p>
                      )}
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => openEdit(wf)}
                      title="Edit"
                    >
                      <Pencil className="h-3 w-3" />
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => toggleWorkflow.mutate({ id: wf.id, enabled: !wf.enabled })}
                      title={wf.enabled ? "Deactivate" : "Activate"}
                    >
                      {wf.enabled ? <PowerOff className="h-3 w-3" /> : <Power className="h-3 w-3" />}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        if (window.confirm(`Delete workflow "${wf.name}"?`)) {
                          deleteWorkflow.mutate(wf.id);
                        }
                      }}
                      title="Delete"
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                  {expanded[wf.id] && (
                    <div className="mt-3 space-y-1 pl-7">
                      {wf.steps.map((s, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          <span className="w-12 font-mono text-muted-foreground">{s.id}</span>
                          <Badge variant="outline" className="text-[10px]">
                            {s.dynamic ? "dynamic" : s.workflow_ref ? `ref:${s.workflow_ref}` : s.template ? `template:${s.template}` : s.intent || s.capability}
                          </Badge>
                          <span className="text-muted-foreground">{s.description}</span>
                          {s.requires_input && s.question && <span className="text-muted-foreground/70">“{s.question}”</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
