import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Loader2, Power, PowerOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToggleWorkflow, useWorkflow, useWorkflowInstances } from "@/hooks/use-workflows";

export default function WorkflowDetailPage() {
  const { id = "" } = useParams();
  const { data: workflow, isLoading, isError } = useWorkflow(id);
  const { data: instances, isLoading: instancesLoading } = useWorkflowInstances(id);
  const toggle = useToggleWorkflow();

  if (isLoading) {
    return <div className="p-6 flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading workflow…</div>;
  }
  if (isError || !workflow) {
    return <div className="p-6 text-sm text-destructive">Could not load workflow.</div>;
  }

  return (
    <div className="space-y-6 p-6 max-w-5xl">
      <Link to="/workflows" className="text-sm text-muted-foreground hover:text-foreground inline-flex items-center gap-1">
        <ArrowLeft className="h-3 w-3" /> Workflows
      </Link>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold">{workflow.name}</h1>
            <Badge variant={workflow.enabled ? "success" : "secondary"}>{workflow.enabled ? "Active" : "Inactive"}</Badge>
            <Badge variant="outline">v{workflow.version}</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">{workflow.description || "No description"}</p>
          {workflow.trigger_intent_pattern && <p className="text-xs font-mono text-muted-foreground mt-2">pattern: {workflow.trigger_intent_pattern}</p>}
        </div>
        <Button
          variant="outline"
          disabled={toggle.isPending}
          onClick={() => toggle.mutate({ id: workflow.id, enabled: !workflow.enabled })}
        >
          {workflow.enabled ? <PowerOff className="h-4 w-4" /> : <Power className="h-4 w-4" />}
          {workflow.enabled ? "Deactivate" : "Activate"}
        </Button>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">Definition ({workflow.steps.length} steps)</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {workflow.steps.map((step, index) => (
            <div key={step.id} className="flex items-center gap-3 rounded-md border p-3 text-sm">
              <span className="w-8 text-xs text-muted-foreground">#{index + 1}</span>
              <span className="font-mono text-xs">{step.id}</span>
              <Badge variant="outline" className="text-[10px]">
                {step.dynamic ? "dynamic" : step.workflow_ref ? `ref:${step.workflow_ref}` : step.template ? `template:${step.template}` : step.intent || step.capability || "step"}
              </Badge>
              <span className="text-muted-foreground">{step.description || ""}</span>
              {step.requires_input && <Badge variant="secondary" className="ml-auto">input required</Badge>}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Instances</CardTitle></CardHeader>
        <CardContent>
          {instancesLoading ? <p className="text-sm text-muted-foreground">Loading instances…</p> : (instances?.instances.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground">No instances for this workflow.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="border-b text-left text-xs text-muted-foreground"><th className="px-3 py-2">Status</th><th className="px-3 py-2">Session</th><th className="px-3 py-2">Step</th><th className="px-3 py-2">Started</th><th className="px-3 py-2">Completed</th></tr></thead>
                <tbody>
                  {instances?.instances.map((instance) => (
                    <tr key={instance.id} className="border-b last:border-0">
                      <td className="px-3 py-2"><Badge variant="outline">{instance.status}</Badge></td>
                      <td className="px-3 py-2">{instance.session_id ? <Link className="text-primary hover:underline" to={`/chat?session=${instance.session_id}`}>{instance.session_id.slice(0, 8)}…</Link> : "—"}</td>
                      <td className="px-3 py-2">{instance.current_step ?? "—"}</td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{instance.started_at ? new Date(instance.started_at).toLocaleString() : "—"}</td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{instance.completed_at ? new Date(instance.completed_at).toLocaleString() : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
