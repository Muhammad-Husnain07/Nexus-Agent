import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { HelpCircle, Save } from "lucide-react"
import { useThemeStore } from "@/store"
import { toast } from "sonner"
import { useState } from "react"

export default function SettingsPage() {
  const { theme, setTheme } = useThemeStore()
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
    <div className="max-w-2xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Settings</h1>
        <Button onClick={handleSave} disabled={saving}>
          <Save size={14} /> {saving ? "Saving..." : "Save"}
        </Button>
      </div>

      <Tabs value="general" onValueChange={() => {}}>
        <TabsList>
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="agent">Agent</TabsTrigger>
          <TabsTrigger value="about">About</TabsTrigger>
        </TabsList>

        <TabsContent value="general" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Display
                <Tooltip>
                  <TooltipTrigger><HelpCircle size={14} className="text-muted-foreground" /></TooltipTrigger>
                  <TooltipContent>Visual preferences for the management console</TooltipContent>
                </Tooltip>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <Label>Dark Mode</Label>
                  <p className="text-xs text-muted-foreground">Switch between light and dark theme</p>
                </div>
                <Switch checked={darkMode} onCheckedChange={setDarkMode} />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <Label>Show Timestamps</Label>
                  <p className="text-xs text-muted-foreground">Display message timestamps in chat</p>
                </div>
                <Switch checked={showTimestamps} onCheckedChange={setShowTimestamps} />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <Label>Stream Responses</Label>
                  <p className="text-xs text-muted-foreground">Stream agent responses token-by-token</p>
                </div>
                <Switch checked={streamResponses} onCheckedChange={setStreamResponses} />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="agent" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Agent Configuration
                <Tooltip>
                  <TooltipTrigger><HelpCircle size={14} className="text-muted-foreground" /></TooltipTrigger>
                  <TooltipContent>These settings are applied on the backend</TooltipContent>
                </Tooltip>
              </CardTitle>
              <CardDescription>Manage your Nexus Agent instance behaviour</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div>
                <Label>LLM Model</Label>
                <p className="text-xs text-muted-foreground">Configured on the backend via <code>NEXUS_LLM__DEFAULT_MODEL</code></p>
              </div>
              <div>
                <Label>Tools</Label>
                <p className="text-xs text-muted-foreground">Manage tools from the <a href="/tools" className="underline">Tools page</a></p>
              </div>
              <div>
                <Label>Memory</Label>
                <p className="text-xs text-muted-foreground">View extracted memories on the <a href="/memory" className="underline">Memory page</a></p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="about" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Nexus Agent</CardTitle>
              <CardDescription>Production-grade agent orchestration platform</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-muted-foreground">Version</span><span>0.1.0</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Architecture</span><span>5-node LangGraph</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">LLM Backend</span><span>NVIDIA NIM / LiteLLM</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Database</span><span>PostgreSQL 16 + pgvector</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Cache</span><span>Redis 7</span></div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
