import { useState, useMemo } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { ScrollArea } from "@/components/ui/scroll-area"
import { copyToClipboard } from "@/lib/utils"
import { Copy, Eye, RefreshCw, Globe, Palette, Shield, Code, MessageSquare } from "lucide-react"

const POSITIONS = [
  { value: "bottom-right", label: "Bottom Right" },
  { value: "bottom-left", label: "Bottom Left" },
  { value: "floating-button", label: "Floating Button" },
]

export default function EmbedGenerator() {
  const [theme, setTheme] = useState("light")
  const [primaryColor, setPrimaryColor] = useState("#2563eb")
  const [position, setPosition] = useState("bottom-right")
  const [welcomeMessage, setWelcomeMessage] = useState("Hello! How can I help you today?")
  const [allowedDomains, setAllowedDomains] = useState("")
  const [maxHeight, setMaxHeight] = useState(600)
  const [maxWidth, setMaxWidth] = useState(380)
  const [customCss, setCustomCss] = useState("")
  const [rateLimit, setRateLimit] = useState(30)
  const [analytics, setAnalytics] = useState(true)
  const [embedToken, setEmbedToken] = useState("")
  const [activeCodeTab, setActiveCodeTab] = useState("script")

  const apiUrl = import.meta.env.VITE_API_URL || "https://api.nexus.example.com"

  const generateToken = () => {
    setEmbedToken(`nex_${crypto.randomUUID().replace(/-/g, "").substring(0, 32)}`)
  }

  const scriptSnippet = useMemo(() => {
    const domainAttr = allowedDomains ? `\n  data-allowed-domains="${allowedDomains}"` : ""
    const cssAttr = customCss ? `\n  data-custom-css="${btoa(customCss)}"` : ""
    return `<script src="${apiUrl}/embed/widget.js"></script>
<script>
  NexusEmbed.init({
    apiUrl: "${apiUrl}",
    token: "${embedToken || "YOUR_TOKEN"}",
    theme: "${theme}",
    primaryColor: "${primaryColor}",
    position: "${position}",
    welcomeMessage: "${welcomeMessage}"${domainAttr}${cssAttr},
    maxHeight: ${maxHeight},
    maxWidth: ${maxWidth},
  });
</script>`
  }, [apiUrl, embedToken, theme, primaryColor, position, welcomeMessage, allowedDomains, customCss, maxHeight, maxWidth])

  const iframeSnippet = useMemo(() => {
    return `<iframe
  src="${apiUrl}/embed/chat?token=${embedToken || "YOUR_TOKEN"}&theme=${theme}&primary=${primaryColor.replace("#", "")}"
  style="position:fixed;bottom:20px;right:20px;width:${maxWidth}px;height:${maxHeight}px;border:none;z-index:999999"
  title="Nexus Chat Widget"
></iframe>`
  }, [apiUrl, embedToken, theme, primaryColor, maxHeight, maxWidth])

  const reactSnippet = `import { NexusEmbed } from "@nexus/embed-widget";

function App() {
  useEffect(() => {
    NexusEmbed.init({
      apiUrl: "${apiUrl}",
      token: "${embedToken || "YOUR_TOKEN"}",
      theme: "${theme}",
      primaryColor: "${primaryColor}",
    });
  }, []);

  return <div>{/* Your app */}</div>;
}`

  const wordpressSnippet = `add_action('wp_footer', function() {
  if (is_admin()) return;
  ?>
  <script src="${apiUrl}/embed/widget.js"></script>
  <script>
    NexusEmbed.init({
      apiUrl: '${apiUrl}',
      token: '${embedToken || "YOUR_TOKEN"}',
      theme: '${theme}',
    });
  </script>
  <?php
});`

  const shopifySnippet = `{% layout none %}
<script src="{{ '${apiUrl}/embed/widget.js' | script_tag }}"></script>
<script>
  NexusEmbed.init({
    apiUrl: '${apiUrl}',
    token: '${embedToken || "YOUR_TOKEN"}',
    theme: '${theme}',
  });
</script>`

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Embed Widget Generator</h1>
          <p className="text-muted-foreground">Create an embeddable chat widget for your website</p>
        </div>
        <Button variant="outline" onClick={() => window.open(`/embed/chat?token=${embedToken}&theme=${theme}`, "_blank")}>
          <Eye className="h-4 w-4 mr-1" /> Preview
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Configuration form */}
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><Palette className="h-4 w-4" /> Appearance</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>Theme</Label>
                  <Select
                    value={theme} onChange={(e) => setTheme(e.target.value)}
                    options={[{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }, { value: "custom", label: "Custom" }]}
                  />
                </div>
                <div>
                  <Label>Primary Color</Label>
                  <div className="flex gap-2 mt-1">
                    <input type="color" value={primaryColor} onChange={(e) => setPrimaryColor(e.target.value)} className="h-9 w-9 rounded cursor-pointer" />
                    <Input value={primaryColor} onChange={(e) => setPrimaryColor(e.target.value)} />
                  </div>
                </div>
              </div>
              <div>
                <Label>Position</Label>
                <Select value={position} onChange={(e) => setPosition(e.target.value)} options={POSITIONS} />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><MessageSquare className="h-4 w-4" /> Content</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label>Welcome Message</Label>
                <Input value={welcomeMessage} onChange={(e) => setWelcomeMessage(e.target.value)} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>Max Width (px)</Label>
                  <Input type="number" value={maxWidth} onChange={(e) => setMaxWidth(Number(e.target.value))} />
                </div>
                <div>
                  <Label>Max Height (px)</Label>
                  <Input type="number" value={maxHeight} onChange={(e) => setMaxHeight(Number(e.target.value))} />
                </div>
              </div>
              <div>
                <Label>Custom CSS</Label>
                <Textarea
                  value={customCss}
                  onChange={(e) => setCustomCss(e.target.value)}
                  placeholder=".nexus-widget { ... }"
                  rows={4}
                  className="font-mono text-sm"
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><Shield className="h-4 w-4" /> Security</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label>Allowed Domains (one per line)</Label>
                <Textarea
                  value={allowedDomains}
                  onChange={(e) => setAllowedDomains(e.target.value)}
                  placeholder="example.com&#10;my-app.vercel.app"
                  rows={3}
                />
                <p className="text-xs text-muted-foreground mt-1">Restrict widget to specific domains for CORS protection</p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>Rate Limit (msg/min)</Label>
                  <Input type="number" value={rateLimit} onChange={(e) => setRateLimit(Number(e.target.value))} />
                </div>
                <div className="flex items-end pb-2">
                  <div className="flex items-center gap-2">
                    <Switch checked={analytics} onCheckedChange={setAnalytics} />
                    <Label>Enable Analytics</Label>
                  </div>
                </div>
              </div>
              <div>
                <Label>Embed Token</Label>
                <div className="flex gap-2 mt-1">
                  <Input
                    value={embedToken}
                    onChange={(e) => setEmbedToken(e.target.value)}
                    placeholder="Click generate to create a unique token"
                    className="font-mono text-xs"
                  />
                  <Button variant="outline" onClick={generateToken}>
                    <RefreshCw className="h-4 w-4 mr-1" /> Generate
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Code snippets */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2"><Code className="h-4 w-4" /> Embed Code</CardTitle>
              <CardDescription>Copy and paste into your website</CardDescription>
            </CardHeader>
            <CardContent>
              <Tabs value={activeCodeTab} onValueChange={setActiveCodeTab}>
                <TabsList className="w-full">
                  <TabsTrigger value="script" className="flex-1 text-xs">Script</TabsTrigger>
                  <TabsTrigger value="iframe" className="flex-1 text-xs">iframe</TabsTrigger>
                </TabsList>
                <TabsContent value="script">
                  <ScrollArea className="h-64">
                    <pre className="text-xs font-mono whitespace-pre-wrap bg-muted p-3 rounded-md">{scriptSnippet}</pre>
                  </ScrollArea>
                </TabsContent>
                <TabsContent value="iframe">
                  <ScrollArea className="h-64">
                    <pre className="text-xs font-mono whitespace-pre-wrap bg-muted p-3 rounded-md">{iframeSnippet}</pre>
                  </ScrollArea>
                </TabsContent>
              </Tabs>
              <Button className="w-full mt-2" variant="outline" size="sm" onClick={() => copyToClipboard(activeCodeTab === "script" ? scriptSnippet : iframeSnippet)}>
                <Copy className="h-4 w-4 mr-1" /> Copy to Clipboard
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2"><Globe className="h-4 w-4" /> Integration Examples</CardTitle>
            </CardHeader>
            <CardContent>
              <Tabs value={activeCodeTab} onValueChange={setActiveCodeTab}>
                <TabsList className="w-full flex-wrap">
                  <TabsTrigger value="script" className="flex-1 text-xs">HTML</TabsTrigger>
                  <TabsTrigger value="react" className="flex-1 text-xs">React</TabsTrigger>
                  <TabsTrigger value="wordpress" className="flex-1 text-xs">WP</TabsTrigger>
                  <TabsTrigger value="shopify" className="flex-1 text-xs">Shopify</TabsTrigger>
                </TabsList>
                <TabsContent value="react">
                  <ScrollArea className="h-48">
                    <pre className="text-xs font-mono whitespace-pre-wrap bg-muted p-3 rounded-md">{reactSnippet}</pre>
                  </ScrollArea>
                </TabsContent>
                <TabsContent value="wordpress">
                  <ScrollArea className="h-48">
                    <pre className="text-xs font-mono whitespace-pre-wrap bg-muted p-3 rounded-md">{wordpressSnippet}</pre>
                  </ScrollArea>
                </TabsContent>
                <TabsContent value="shopify">
                  <ScrollArea className="h-48">
                    <pre className="text-xs font-mono whitespace-pre-wrap bg-muted p-3 rounded-md">{shopifySnippet}</pre>
                  </ScrollArea>
                </TabsContent>
                <TabsContent value="script">
                  <ScrollArea className="h-48">
                    <pre className="text-xs font-mono whitespace-pre-wrap bg-muted p-3 rounded-md">{scriptSnippet}</pre>
                  </ScrollArea>
                </TabsContent>
              </Tabs>
              <Button className="w-full mt-2" variant="outline" size="sm" onClick={() => {
                const snippets: Record<string, string> = { script: scriptSnippet, iframe: iframeSnippet, react: reactSnippet, wordpress: wordpressSnippet, shopify: shopifySnippet }
                copyToClipboard(snippets[activeCodeTab] || scriptSnippet)
              }}>
                <Copy className="h-4 w-4 mr-1" /> Copy Code
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

