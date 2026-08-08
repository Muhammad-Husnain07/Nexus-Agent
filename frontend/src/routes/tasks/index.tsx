import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { useTasksList, useCreateTask, useTaskAction } from "@/hooks/use-workflows-api";
import { Pause, Play, X, Plus } from "lucide-react";

const STATUS_VARIANTS: Record<string, string> = {
  queued: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-400",
  running: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400",
  paused: "bg-muted text-muted-foreground",
  completed: "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400",
  failed: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400",
  cancelled: "bg-muted text-muted-foreground",
};

export default function TasksPage() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const { data, isLoading } = useTasksList(statusFilter || undefined);
  const createTask = useCreateTask();
  const taskAction = useTaskAction();

  const [showCreate, setShowCreate] = useState(false);
  const [taskType, setTaskType] = useState("");
  const [payloadText, setPayloadText] = useState("{}");
  const [scheduleCron, setScheduleCron] = useState("");
  const [nextRunAt, setNextRunAt] = useState("");
  const [maxAttempts, setMaxAttempts] = useState(3);
  const [sessionId, setSessionId] = useState("");

  const handleCreate = async () => {
    if (!taskType.trim()) {
      toast.error("Task type is required");
      return;
    }
    let payload: Record<string, unknown> = {};
    try {
      payload = payloadText.trim() ? JSON.parse(payloadText) : {};
    } catch {
      toast.error("Payload must be valid JSON");
      return;
    }
    try {
      await createTask.mutateAsync({
        task_type: taskType.trim(),
        payload,
        ...(scheduleCron.trim() ? { schedule_cron: scheduleCron.trim() } : {}),
        ...(nextRunAt.trim() ? { next_run_at: nextRunAt.trim() } : {}),
        ...(maxAttempts !== 3 ? { max_attempts: maxAttempts } : {}),
        ...(sessionId.trim() ? { session_id: sessionId.trim() } : {}),
      });
      setShowCreate(false);
      setTaskType("");
      setPayloadText("{}");
      setScheduleCron("");
      setNextRunAt("");
      setMaxAttempts(3);
      setSessionId("");
      toast.success("Task created");
    } catch {
      toast.error("Failed to create task");
    }
  };

  const act = async (id: string, action: "pause" | "resume" | "cancel") => {
    try {
      await taskAction.mutateAsync({ id, action });
      toast.success(`Task ${action}d`);
    } catch {
      toast.error(`Failed to ${action} task`);
    }
  };

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Tasks</h1>
          <p className="text-sm text-muted-foreground">
            Long-running orchestration jobs processed by the worker.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-md border bg-background px-3 py-2 text-sm"
          >
            <option value="">All statuses</option>
            <option value="queued">Queued</option>
            <option value="running">Running</option>
            <option value="paused">Paused</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
          </select>
          <Button onClick={() => setShowCreate((v) => !v)}>
            <Plus className="h-4 w-4" /> New Task
          </Button>
        </div>
      </div>

      {showCreate && (
        <Card>
          <CardHeader><CardTitle className="text-base">Create background task</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">Task type *</p>
                <Input
                  placeholder="e.g. workflow_run"
                  value={taskType}
                  onChange={(e) => setTaskType(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">Max attempts</p>
                <Input
                  type="number"
                  min={1}
                  max={10}
                  value={maxAttempts}
                  onChange={(e) => setMaxAttempts(Number(e.target.value) || 3)}
                />
              </div>
            </div>
            <textarea
              placeholder='Payload JSON (e.g. {"workflow": "invoice_approval"})'
              value={payloadText}
              onChange={(e) => setPayloadText(e.target.value)}
              rows={3}
              className="w-full rounded-md border bg-background px-3 py-2 font-mono text-xs outline-none focus:ring-2 focus:ring-ring"
            />
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">Cron schedule (optional)</p>
                <Input
                  placeholder="e.g. 0 9 * * 1"
                  value={scheduleCron}
                  onChange={(e) => setScheduleCron(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">Run at (optional, ISO)</p>
                <Input
                  placeholder="e.g. 2026-08-03T09:00:00Z"
                  value={nextRunAt}
                  onChange={(e) => setNextRunAt(e.target.value)}
                />
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground">Session id (optional)</p>
              <Input
                placeholder="Originating conversation session"
                value={sessionId}
                onChange={(e) => setSessionId(e.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <Button onClick={handleCreate} disabled={createTask.isPending}>Create</Button>
              <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6 text-sm text-muted-foreground">Loading tasks…</div>
          ) : (data?.tasks?.length ?? 0) === 0 ? (
            <div className="p-6 text-sm text-muted-foreground">No tasks yet.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="px-4 py-3">Type</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Attempts</th>
                    <th className="px-4 py-3">Schedule</th>
                    <th className="px-4 py-3">Created</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.tasks?.map((t) => (
                    <tr key={t.id} className="border-b last:border-0">
                      <td className="px-4 py-3 font-mono text-xs">{t.task_type}</td>
                      <td className="px-4 py-3">
                        <Badge className={STATUS_VARIANTS[t.status] ?? ""}>{t.status}</Badge>
                      </td>
                      <td className="px-4 py-3">{t.attempts}/{t.max_attempts}</td>
                      <td className="px-4 py-3 font-mono text-xs">{t.schedule_cron ?? "—"}</td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {t.created_at ? new Date(t.created_at).toLocaleString() : "—"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex justify-end gap-1">
                          {t.status === "running" && (
                            <Button size="sm" variant="outline" onClick={() => act(t.id, "pause")} title="Pause">
                              <Pause className="h-3 w-3" />
                            </Button>
                          )}
                          {t.status === "paused" && (
                            <Button size="sm" variant="outline" onClick={() => act(t.id, "resume")} title="Resume">
                              <Play className="h-3 w-3" />
                            </Button>
                          )}
                          {!["completed", "cancelled", "failed"].includes(t.status) && (
                            <Button size="sm" variant="outline" onClick={() => act(t.id, "cancel")} title="Cancel">
                              <X className="h-3 w-3" />
                            </Button>
                          )}
                        </div>
                      </td>
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
