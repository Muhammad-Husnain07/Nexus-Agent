import { useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import ChatWidget from "@/components/embed/chat-widget";
import { Code2, Copy, Check, Monitor, ExternalLink, Puzzle, AlertTriangle, CircleCheck } from "lucide-react";
import { useState as useReactState } from "react";

/**
 * Widget Embed Studio — configure the embeddable assistant widget visually,
 * preview it live, and copy the HTML snippet to embed it in ANY application.
 *
 * The snippet references the built widget bundle (dist-embed/embed-widget.js)
 * served from this console's origin, plus the console's API base — so the
 * same widget works in any third-party site that can reach this backend.
 */
export default function WidgetStudioPage() {
  const [apiBase, setApiBase] = useState("/api/v1");
  const [title, setTitle] = useState("Assistant");
  const [greeting, setGreeting] = useState("Hi! Ask me anything about your application.");
  const [placeholder, setPlaceholder] = useState("Type a message…");
  const [primary, setPrimary] = useState("#635bff");
  const [launcher, setLauncher] = useState(true);
  const [position, setPosition] = useState("bottom-right");
  const [height, setHeight] = useState(520);
  const [width, setWidth] = useState(380);
  const [persistSession, setPersistSession] = useState(true);
  const [copied, setCopied] = useState(false);
  const [tab, setTab] = useState("html");
  const [showAdvanced, setShowAdvanced] = useReactState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const [bundleState, setBundleState] = useState<"unknown" | "checking" | "ready" | "missing">("unknown");

  const previewConfig = useMemo(() => ({
    apiBase,
    title,
    greeting,
    placeholder,
    primary,
    launcher,
    position,
    height,
    width,
    persistSession,
    preview: true,
  }), [apiBase, title, greeting, placeholder, primary, launcher, position, height, width, persistSession]);

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const widgetSrc = `${origin}/dist-embed/embed-widget.js`;
  const resolvedApi = apiBase.trim() || "/api/v1";

  const htmlSnippet = useMemo(() => {
    const attrs = [
      `data-nexus-chat`,
      apiBase.trim() ? `data-api-base="${resolvedApi}"` : null,
      title.trim() ? `data-title="${title.trim()}"` : null,
      greeting.trim() ? `data-greeting="${greeting.trim()}"` : null,
      placeholder.trim() ? `data-placeholder="${placeholder.trim()}"` : null,
      primary.trim() ? `data-primary="${primary.trim()}"` : null,
      launcher ? `data-launcher="true"` : null,
      position !== "bottom-right" ? `data-position="${position}"` : null,
      height !== 520 ? `data-height="${height}"` : null,
      width !== 380 ? `data-width="${width}"` : null,
      !persistSession ? `data-persist-session="false"` : null,
    ].filter(Boolean).join("\n     ");

    return `<!-- Nexus assistant widget — drop anywhere -->
<div
     ${attrs}
     style="position:${launcher ? "fixed" : "relative"}; ${launcher ? `${position.split("-").join(": 16px; ")}: 16px` : ""}; z-index: 2147483000">
</div>
<script src="${widgetSrc}"></script>`;
  }, [apiBase, title, greeting, placeholder, primary, launcher, position, height, width, persistSession, resolvedApi, widgetSrc]);

  const jsSnippet = useMemo(() => {
    const opts = [
      `  apiBase: ${JSON.stringify(resolvedApi)},`,
      `  title: ${JSON.stringify(title)},`,
      `  greeting: ${JSON.stringify(greeting)},`,
      `  placeholder: ${JSON.stringify(placeholder)},`,
      `  primary: ${JSON.stringify(primary)},`,
      `  launcher: ${launcher},`,
      `  position: ${JSON.stringify(position)},`,
      `  height: ${height},`,
      `  width: ${width},`,
      `  persistSession: ${persistSession},`,
      `  onEvent: function (type, payload) { console.log("nexus event", type, payload); },`,
    ].join("\n");
    return (
      "<!-- Nexus assistant widget (programmatic) -->\n" +
      '<div id="nexus-assistant"></div>\n' +
      `<script src="${widgetSrc}"></script>\n` +
      "<script>\n" +
      '  window.NexusEmbed.mount(document.getElementById("nexus-assistant"), {\n' +
      opts +
      "\n  });\n" +
      "</script>"
    );
  }, [resolvedApi, title, greeting, placeholder, primary, launcher, position, height, width, persistSession, widgetSrc]);

  const copy = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast.success(`${what} copied`);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      toast.error("Copy failed — select and copy manually");
    }
  };

  const validateConfig = () => {
    const trimmedApi = apiBase.trim();
    if (!trimmedApi) return setConfigError("API base URL is required.");
    if (!/^https?:\/\//.test(trimmedApi) && !trimmedApi.startsWith("/")) {
      return setConfigError("API base URL must be an absolute HTTP(S) URL or a local /api path.");
    }
    if (!title.trim()) return setConfigError("Widget title is required.");
    if (!/^#[0-9a-f]{6}$/i.test(primary.trim())) return setConfigError("Primary color must be a six-digit hex color.");
    if (width < 280 || width > 560 || height < 320 || height > 900) return setConfigError("Widget dimensions are outside the supported range.");
    setConfigError(null);
    toast.success("Widget configuration is valid");
  };

  const verifyBundle = async () => {
    setBundleState("checking");
    try {
      const response = await fetch("/dist-embed/embed-widget.js", { method: "HEAD" });
      setBundleState(response.ok ? "ready" : "missing");
      if (!response.ok) toast.error("Embed bundle is not built. Run npm run build:embed.");
      else toast.success("Embed bundle is ready");
    } catch {
      setBundleState("missing");
      toast.error("Could not verify the embed bundle.");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Puzzle className="h-6 w-6 text-primary" /> Widget Embed Studio
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Configure the assistant widget, preview it live, and embed it in any application with one snippet.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={validateConfig}>Validate configuration</Button>
          <Button variant="outline" onClick={() => void verifyBundle()} disabled={bundleState === "checking"}>
            {bundleState === "ready" ? <CircleCheck className="h-4 w-4 text-green-500" /> : <Code2 className="h-4 w-4" />}
            {bundleState === "checking" ? "Checking…" : "Verify bundle"}
          </Button>
          <Button variant="outline" onClick={() => window.open(widgetSrc, "_blank")}>
          <ExternalLink className="h-4 w-4" /> Open widget bundle
          </Button>
        </div>
      </div>

      {configError && <div role="alert" className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"><AlertTriangle className="h-4 w-4" />{configError}</div>}
      {bundleState === "missing" && <div role="alert" className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-600 dark:text-amber-400">Build the embed artifact with <code>npm run build:embed</code> before opening the bundle or deploying the snippet.</div>}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* ── Configuration ── */}
        <Card className="card-hover">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Monitor className="h-4 w-4 text-primary" /> Appearance & behaviour
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>API base URL</Label>
                <Input value={apiBase} onChange={(e) => setApiBase(e.target.value)} placeholder="/api/v1" className="font-mono text-xs" />
              </div>
              <div className="space-y-1.5">
                   <Label htmlFor="widget-title">Widget title</Label>
                   <Input id="widget-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Assistant" />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>Greeting message</Label>
              <Input value={greeting} onChange={(e) => setGreeting(e.target.value)} placeholder="Hi! Ask me anything…" />
            </div>

            <div className="space-y-1.5">
              <Label>Input placeholder</Label>
              <Input value={placeholder} onChange={(e) => setPlaceholder(e.target.value)} placeholder="Type a message…" />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>Primary color</Label>
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    value={primary}
                    onChange={(e) => setPrimary(e.target.value)}
                    className="h-9 w-12 shrink-0 cursor-pointer rounded-md border bg-transparent"
                  />
                  <Input value={primary} onChange={(e) => setPrimary(e.target.value)} className="font-mono text-xs" />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>Launcher position</Label>
                <select
                  value={position}
                  onChange={(e) => setPosition(e.target.value)}
                  className="h-9 w-full rounded-md border bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  <option value="bottom-right">Bottom right</option>
                  <option value="bottom-left">Bottom left</option>
                  <option value="top-right">Top right</option>
                  <option value="top-left">Top left</option>
                </select>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>Width (px)</Label>
                <Input type="number" value={width} onChange={(e) => setWidth(Number(e.target.value) || 380)} min={280} max={560} />
              </div>
              <div className="space-y-1.5">
                <Label>Height (px)</Label>
                <Input type="number" value={height} onChange={(e) => setHeight(Number(e.target.value) || 520)} min={320} max={900} />
              </div>
            </div>

            <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
              <div className="flex items-center justify-between">
                <div>
                  <Label>Floating launcher</Label>
                  <p className="text-xs text-muted-foreground">Show as a chat bubble instead of an inline panel</p>
                </div>
                <Switch checked={launcher} onCheckedChange={setLauncher} />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <Label>Persist session</Label>
                  <p className="text-xs text-muted-foreground">Keep the conversation across page reloads (localStorage)</p>
                </div>
                <Switch checked={persistSession} onCheckedChange={setPersistSession} />
              </div>
              <button
                className="text-xs text-primary hover:underline"
                onClick={() => setShowAdvanced((v) => !v)}
              >
                {showAdvanced ? "Hide" : "Show"} widget notes
              </button>
              {showAdvanced && (
                <p className="text-xs text-muted-foreground leading-relaxed">
                   The bundle is built with <code className="rounded bg-muted-foreground/10 px-1">npm run build:embed</code> into{" "}
                  <code className="rounded bg-muted-foreground/10 px-1">dist-embed/embed-widget.js</code>. Host it on any static
                  server/CDN and point <code className="rounded bg-muted-foreground/10 px-1">data-api-base</code> at a Nexus API —
                  no build step needed on the embedding site.
                </p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* ── Live preview ── */}
        <div className="space-y-6">
          <Card className="card-hover">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <Puzzle className="h-4 w-4 text-primary" /> Live preview
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="relative flex min-h-[430px] items-start justify-center overflow-hidden rounded-xl border bg-gradient-to-br from-muted/40 to-background dot-grid p-6">
                {launcher ? (
                  <div className="flex w-full items-start justify-center pt-4">
                    <ChatWidget {...previewConfig} />
                  </div>
                ) : (
                  <ChatWidget {...previewConfig} />
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* ── Embed code ── */}
      <Card className="card-hover">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Code2 className="h-4 w-4 text-primary" /> Embed snippet
          </CardTitle>
          <Button
            size="sm"
            onClick={() => copy(tab === "html" ? htmlSnippet : jsSnippet, "Embed snippet")}
          >
            {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />} {copied ? "Copied!" : "Copy"}
          </Button>
        </CardHeader>
        <CardContent>
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value="html">HTML (data attributes)</TabsTrigger>
              <TabsTrigger value="js">Programmatic (JS)</TabsTrigger>
            </TabsList>
            <TabsContent value="html">
              <pre className="mt-3 max-h-72 overflow-auto rounded-lg border bg-muted/40 p-4 text-xs leading-relaxed whitespace-pre">
                {htmlSnippet}
              </pre>
            </TabsContent>
            <TabsContent value="js">
              <pre className="mt-3 max-h-72 overflow-auto rounded-lg border bg-muted/40 p-4 text-xs leading-relaxed whitespace-pre">
                {jsSnippet}
              </pre>
            </TabsContent>
          </Tabs>
          <p className="mt-3 text-xs text-muted-foreground">
            Paste this snippet into any page (plain HTML, React, Vue, WordPress, etc.). The widget auto-mounts on the{" "}
            <code className="rounded bg-muted-foreground/10 px-1">data-nexus-chat</code> element and talks to your Nexus backend.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
