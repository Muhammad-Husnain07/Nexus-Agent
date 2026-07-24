import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Save, HelpCircle, Sun, Bot, Info, Monitor } from "lucide-react"
import { useThemeStore } from "@/store"
import { toast } from "sonner"
import { useState } from "react"

export default function SettingsPage() {
  const { theme, setTheme } = useThemeStore()
  const [tab, setTab] = useState("general")
  const [darkMode, setDarkMode] = useState(theme === "dark")
  const [streamResponses, setStreamResponses] = useState(true)
  const [showTimestamps, setShowTimestamps] = useState(true)
  const [saving, setSaving] = useState(false)

  const handleSave = () => {
    setSaving(true)
    setTheme(darkMode ? "dark" : "light")
    setTimeout(() => { setSaving(false); toast.success("Settings saved") }, 300)
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Settings</h1>
          <p className="text-sm text-muted-foreground">Manage your Nexus Agent preferences</p>
        </div>
        <Button onClick={handleSave} disabled={saving}><Save size={14} /> {saving ? "Saving..." : "Save"}</Button>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="w-full justify-start bg-transparent border-b rounded-none h-auto p-0 gap-0">
          {[{ value: "general", label: "General", icon: Monitor }, { value: "agent", label: "Agent", icon: Bot }, { value: "about", label: "About", icon: Info }].map((t) => (
            <TabsTrigger key={t.value} value={t.value}
              className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent px-4 py-3 gap-2">
              <t.icon size={14} /> {t.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="general" className="space-y-4 pt-4">
          <Card className="card-hover">
            <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Sun size={16} /> Display</CardTitle></CardHeader>
            <CardContent className="space-y-5">
              <div className="flex items-center justify-between">
                <div><Label>Dark Mode</Label><p className="text-xs text-muted-foreground">Switch between light and dark theme</p></div>
                <Switch checked={darkMode} onCheckedChange={setDarkMode} />
              </div>
              <div className="flex items-center justify-between">
                <div><Label>Show Timestamps</Label><p className="text-xs text-muted-foreground">Display message timestamps in chat</p></div>
                <Switch checked={showTimestamps} onCheckedChange={setShowTimestamps} />
              </div>
              <div className="flex items-center justify-between">
                <div><Label>Stream Responses</Label><p className="text-xs text-muted-foreground">Stream agent responses token-by-token</p></div>
                <Switch checked={streamResponses} onCheckedChange={setStreamResponses} />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="agent" className="space-y-4 pt-4">
          <Card className="card-hover">
            <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Bot size={16} /> Agent Configuration</CardTitle></CardHeader>
            <CardContent className="space-y-5 text-sm">
              <div className="p-3 rounded-lg bg-muted/50">
                <Label>LLM Model</Label>
                <p className="text-xs text-muted-foreground mt-1">Configured on the backend via <code className="text-[10px] px-1 py-0.5 rounded bg-muted-foreground/10">NEXUS_LLM__DEFAULT_MODEL</code></p>
              </div>
              <div className="p-3 rounded-lg bg-muted/50">
                <Label>Tools</Label>
                <p className="text-xs text-muted-foreground mt-1">Manage tools from the <a href="/tools" className="underline text-primary">Tools page</a></p>
              </div>
              <div className="p-3 rounded-lg bg-muted/50">
                <Label>Memory</Label>
                <p className="text-xs text-muted-foreground mt-1">View extracted memories on the <a href="/memory" className="underline text-primary">Memory page</a></p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="about" className="space-y-4 pt-4">
          <Card className="card-hover">
            <CardHeader><CardTitle className="text-base">Nexus Agent</CardTitle><CardDescription>Production-grade agent orchestration platform</CardDescription></CardHeader>
            <CardContent>
              <div className="space-y-3 text-sm">
                {[{ label: "Version", value: "0.1.0" }, { label: "Architecture", value: "5-node LangGraph" }, { label: "LLM Backend", value: "NVIDIA NIM / LiteLLM" }, { label: "Database", value: "PostgreSQL 16 + pgvector" }, { label: "Cache", value: "Redis 7" }].map((d) => (
                  <div key={d.label} className="flex items-center justify-between p-2 rounded-lg bg-muted/30"><span className="text-muted-foreground">{d.label}</span><span className="font-medium">{d.value}</span></div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
