import { Link, useParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useTask, useTaskAction } from "@/hooks/use-tasks";
import { mapTaskStatus } from "@/api/status";
import { Pause, Play, X, ArrowLeft, Loader2 } from "lucide-react";

const TONE_BADGE: Record<string, string> = {
  success: "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400",
  danger: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400",
  info: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-400",
  warning: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400",
  neutral: "bg-muted text-muted-foreground",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <div className="text-sm break-all">{children}</div>
    </div>
  );
}

export default function TaskDetailPage() {
  const { id = "" } = useParams();
  const { data: task, isLoading } = useTask(id);
  const taskAction = useTaskAction();

  if (isLoading) {
    return (
      <div className="p-6 flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading task…
      </div>
    );
  }
  if (!task) {
    return <div className="p-6 text-sm text-muted-foreground">Task not found.</div>;
  }

  const pres = mapTaskStatus(task.status);

  const act = async (action: "pause" | "resume" | "cancel") => {
    try {
      await taskAction.mutateAsync({ id, action });
      toast.success(`Task ${action}d`);
    } catch {
      toast.error(`Failed to ${action} task`);
    }
  };

  return (
    <div className="space-y-6 p-6 max-w-3xl">
      <div className="flex items-center gap-2">
        <Link to="/tasks" className="text-sm text-muted-foreground hover:text-foreground inline-flex items-center gap-1">
          <ArrowLeft className="h-3 w-3" /> Tasks
        </Link>
      </div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold font-mono">{task.task_type}</h1>
          <p className="text-xs text-muted-foreground">{task.id}</p>
        </div>
        <Badge className={TONE_BADGE[pres.tone] ?? ""} title={pres.description}>{pres.label}</Badge>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">Details</CardTitle></CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <Field label="Session">{task.session_id ? (
            <Link to={`/chat?session=${task.session_id}`} className="text-primary hover:underline">{task.session_id}</Link>
          ) : "—"}</Field>
          <Field label="Attempts">{task.attempts} / {task.max_attempts}</Field>
          <Field label="Created">{task.created_at ? new Date(task.created_at).toLocaleString() : "—"}</Field>
          <Field label="Completed">{task.completed_at ? new Date(task.completed_at).toLocaleString() : "—"}</Field>
          <Field label="Cron">{task.schedule_cron ?? "—"}</Field>
          <Field label="Next run">{task.next_run_at ? new Date(task.next_run_at).toLocaleString() : "—"}</Field>
        </CardContent>
      </Card>

      {task.progress != null && (
        <Card>
          <CardHeader><CardTitle className="text-base">Progress</CardTitle></CardHeader>
          <CardContent>
            <pre className="text-xs whitespace-pre-wrap bg-muted/40 rounded p-3 overflow-auto max-h-64">
              {JSON.stringify(task.progress, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      {task.error_message && (
        <Card className="border-red-500/30">
          <CardHeader><CardTitle className="text-base text-destructive">Error</CardTitle></CardHeader>
          <CardContent>
            <pre className="text-xs whitespace-pre-wrap bg-red-500/5 rounded p-3 overflow-auto max-h-64 text-destructive">
              {task.error_message}
            </pre>
          </CardContent>
        </Card>
      )}

      {task.result != null && (
        <Card>
          <CardHeader><CardTitle className="text-base">Result</CardTitle></CardHeader>
          <CardContent>
            <pre data-testid="task-result" className="text-xs whitespace-pre-wrap bg-muted/40 rounded p-3 overflow-auto max-h-96">
              {typeof task.result === "string" ? task.result : JSON.stringify(task.result, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      <div className="flex gap-2">
        {task.status === "running" && (
          <Button variant="outline" onClick={() => act("pause")}><Pause className="h-4 w-4" /> Pause</Button>
        )}
        {task.status === "paused" && (
          <Button variant="outline" onClick={() => act("resume")}><Play className="h-4 w-4" /> Resume</Button>
        )}
        {!["completed", "cancelled", "failed"].includes(task.status) && (
          <Button variant="destructive" onClick={() => act("cancel")}><X className="h-4 w-4" /> Cancel</Button>
        )}
      </div>
    </div>
  );
}
