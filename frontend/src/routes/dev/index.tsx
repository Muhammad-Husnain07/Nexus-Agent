import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Activity, Braces, Clock3, Code2, GitBranch, Layers3, Search, ShieldAlert, Workflow } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useChatRunStore } from "@/store/chat-run";
import { projectDevEvents, type DevProjection } from "@/api/dev-projections";
import { mapResponseStatus } from "@/api/status";

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="max-h-72 overflow-auto rounded-md bg-muted/40 p-3 text-xs whitespace-pre-wrap">{JSON.stringify(value, null, 2)}</pre>;
}

function EmptyPanel({ children }: { children: React.ReactNode }) {
  return <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">{children}</div>;
}

function Timeline({ projection }: { projection: DevProjection }) {
  if (projection.timeline.length === 0) return <EmptyPanel>Open this console from an active chat run to inspect lifecycle events.</EmptyPanel>;
  return (
    <div className="space-y-1">
      {projection.timeline.map((item) => (
        <div key={`${item.index}-${item.type}`} className="grid grid-cols-[150px_120px_1fr] items-center gap-3 rounded-md border px-3 py-2 text-xs">
          <span className="text-muted-foreground">{new Date(item.timestamp).toLocaleTimeString()}</span>
          <Badge variant="outline" className="w-fit capitalize">{item.phase}</Badge>
          <span><b>{item.type}</b><span className="text-muted-foreground"> · {item.summary}</span></span>
        </div>
      ))}
    </div>
  );
}

function Timing({ projection }: { projection: DevProjection }) {
  const timing = projection.plannerTiming;
  if (!timing) return <EmptyPanel>No planner timing event in this browser-side run.</EmptyPanel>;
  const chunks = (timing.chunk_timing as Record<string, unknown> | undefined) ?? {};
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Metric label="Planner latency" value={`${String(timing.latency_ms ?? 0)} ms`} />
      <Metric label="Chunks" value={String(chunks.chunk_count ?? "—")} />
      <Metric label="Max chunk" value={`${String(chunks.max_chunk_ms ?? "—")} ms`} />
      <Metric label="Sum chunks" value={`${String(chunks.sum_chunk_ms ?? "—")} ms`} />
      <div className="sm:col-span-2 lg:col-span-4"><JsonBlock value={chunks} /></div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md border p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 font-mono text-sm">{value}</p></div>;
}

export default function DeveloperConsolePage() {
  const [searchParams] = useSearchParams();
  const storeSessionId = useChatRunStore((s) => s.sessionId);
  const lifecycle = useChatRunStore((s) => s.lifecycle);
  const [filter, setFilter] = useState("");
  const sessionId = searchParams.get("session") ?? storeSessionId;
  const projection = useMemo(() => projectDevEvents(lifecycle.debugEvents), [lifecycle.debugEvents]);
  const filteredRaw = projection.rawEvents.filter((event) => !filter || event.type.toLowerCase().includes(filter.toLowerCase()));
  const response = lifecycle.responseStatus ? mapResponseStatus(lifecycle.responseStatus) : null;

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2"><Code2 className="h-6 w-6 text-primary" /><h1 className="text-2xl font-semibold">Developer Console</h1></div>
          <p className="mt-1 text-sm text-muted-foreground">A read-only projection of the current typed Nexus event stream.</p>
          {sessionId && <p className="mt-2 font-mono text-xs text-muted-foreground">session: {sessionId}</p>}
        </div>
        <div className="flex items-center gap-2">
          {response && <Badge className={response.tone === "danger" ? "bg-destructive text-destructive-foreground" : ""}>{response.label}</Badge>}
          <Badge variant="outline">phase: {lifecycle.phase}</Badge>
          <Button asChild variant="outline" size="sm"><Link to={sessionId ? `/chat?session=${sessionId}` : "/chat"}>Back to chat</Link></Button>
        </div>
      </div>

      {projection.rawEvents.length === 0 ? (
        <Card><CardContent className="p-6"><EmptyPanel>No live event trail is available. Start a chat run, then open Developer Console; historical events require a backend event-history read endpoint, which is not currently exposed.</EmptyPanel></CardContent></Card>
      ) : (
        <Tabs defaultValue="timeline">
          <TabsList className="flex-wrap h-auto">
            <TabsTrigger value="timeline"><Activity className="mr-1 h-4 w-4" />Timeline</TabsTrigger>
            <TabsTrigger value="planner"><Clock3 className="mr-1 h-4 w-4" />Planner</TabsTrigger>
            <TabsTrigger value="resolution"><ShieldAlert className="mr-1 h-4 w-4" />Resolution</TabsTrigger>
            <TabsTrigger value="execution"><Workflow className="mr-1 h-4 w-4" />Execution</TabsTrigger>
            <TabsTrigger value="maps"><GitBranch className="mr-1 h-4 w-4" />Maps</TabsTrigger>
            <TabsTrigger value="evidence"><Layers3 className="mr-1 h-4 w-4" />Evidence</TabsTrigger>
            <TabsTrigger value="raw"><Braces className="mr-1 h-4 w-4" />Raw events</TabsTrigger>
          </TabsList>

          <TabsContent value="timeline"><Card><CardHeader><CardTitle className="text-base">Run timeline</CardTitle></CardHeader><CardContent><Timeline projection={projection} /></CardContent></Card></TabsContent>
          <TabsContent value="planner"><Card><CardHeader><CardTitle className="text-base">Planner timing</CardTitle></CardHeader><CardContent><Timing projection={projection} /></CardContent></Card></TabsContent>
          <TabsContent value="resolution"><Card><CardHeader><CardTitle className="text-base">Resolver diagnostics</CardTitle></CardHeader><CardContent>{projection.suppressions.length === 0 ? <EmptyPanel>No suppression events in this run.</EmptyPanel> : <div className="space-y-2">{projection.suppressions.map((item, index) => <div key={index} className="rounded-md border p-3 text-xs"><b>{String(item.capability ?? "capability")}</b><p className="mt-1 text-muted-foreground">{String(item.reason ?? "No reason supplied")}</p></div>)}</div>}</CardContent></Card></TabsContent>
          <TabsContent value="execution"><Card><CardHeader><CardTitle className="text-base">Execution</CardTitle></CardHeader><CardContent>{projection.executions.length === 0 ? <EmptyPanel>No tool execution events.</EmptyPanel> : <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b text-left text-xs text-muted-foreground"><th className="px-2 py-2">Task</th><th className="px-2 py-2">Tool</th><th className="px-2 py-2">Status</th><th className="px-2 py-2">Duration</th><th className="px-2 py-2">Cache</th><th className="px-2 py-2">Error</th></tr></thead><tbody>{projection.executions.map((row) => <tr key={row.taskId} className="border-b last:border-0"><td className="px-2 py-2 font-mono text-xs">{row.taskId}</td><td className="px-2 py-2 font-mono text-xs">{row.tool}</td><td className="px-2 py-2"><Badge variant="outline">{row.status}</Badge></td><td className="px-2 py-2 text-xs">{row.durationMs != null ? `${Math.round(row.durationMs)}ms` : "—"}</td><td className="px-2 py-2 text-xs">{row.cached ? "cached" : "—"}</td><td className="px-2 py-2 text-xs text-destructive">{row.error ?? "—"}</td></tr>)}</tbody></table></div>}</CardContent></Card></TabsContent>
          <TabsContent value="maps"><Card><CardHeader><CardTitle className="text-base">Map / fan-out</CardTitle></CardHeader><CardContent>{projection.mapDegradations.length === 0 ? <EmptyPanel>No map degradation events.</EmptyPanel> : <JsonBlock value={projection.mapDegradations} />}</CardContent></Card></TabsContent>
          <TabsContent value="evidence"><Card><CardHeader><CardTitle className="text-base">Evidence / synthesis</CardTitle></CardHeader><CardContent>{projection.evidence ? <JsonBlock value={projection.evidence} /> : <EmptyPanel>No final-response coverage breakdown in this run.</EmptyPanel>}</CardContent></Card></TabsContent>
          <TabsContent value="raw"><Card><CardHeader><div className="flex items-center justify-between gap-3"><CardTitle className="text-base">Raw event inspector</CardTitle><div className="relative w-64"><Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" /><Input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter event name" className="h-8 pl-7 text-xs" /></div></div></CardHeader><CardContent><div className="space-y-2">{filteredRaw.map((event, index) => <details key={`${event.ts}-${index}`} className="rounded-md border"><summary className="cursor-pointer px-3 py-2 text-xs"><span className="font-mono">{event.type}</span><span className="ml-3 text-muted-foreground">{new Date(event.ts).toLocaleTimeString()}</span></summary><div className="border-t p-3"><JsonBlock value={event} /></div></details>)}</div></CardContent></Card></TabsContent>
        </Tabs>
      )}
    </div>
  );
}
