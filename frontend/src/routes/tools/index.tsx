import { useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Plus, Search } from "lucide-react"

const tools = [
  { id: "1", name: "geocode_city", category: "data", risk: "low", enabled: true },
  { id: "2", name: "open_meteo_forecast", category: "data", risk: "low", enabled: true },
  { id: "3", name: "get_joke", category: "entertainment", risk: "low", enabled: true },
]

export default function ToolsListPage() {
  const navigate = useNavigate()

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold tracking-tight">Tools</h1><p className="text-muted-foreground text-sm">Manage your API tools</p></div>
        <Button onClick={() => navigate("/tools/new")}><Plus size={16} /> Create Tool</Button>
      </div>

      <div className="relative max-w-sm">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input placeholder="Search tools..." className="pl-9" />
      </div>

      <Card>
        <CardHeader><CardTitle>All Tools</CardTitle></CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="text-left py-3 px-2 font-medium">Name</th>
                  <th className="text-left py-3 px-2 font-medium">Category</th>
                  <th className="text-left py-3 px-2 font-medium">Risk</th>
                  <th className="text-left py-3 px-2 font-medium">Enabled</th>
                  <th className="text-right py-3 px-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {tools.map((t) => (
                  <tr key={t.id} className="border-b hover:bg-muted/50 cursor-pointer" onClick={() => navigate(`/tools/${t.id}`)}>
                    <td className="py-3 px-2 font-medium">{t.name}</td>
                    <td className="py-3 px-2"><Badge variant="outline">{t.category}</Badge></td>
                    <td className="py-3 px-2"><Badge variant={t.risk === "low" ? "success" : "warning"}>{t.risk}</Badge></td>
                    <td className="py-3 px-2"><span className={`inline-block w-2 h-2 rounded-full ${t.enabled ? "bg-green-500" : "bg-gray-300"}`} /></td>
                    <td className="py-3 px-2 text-right">
                      <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); navigate(`/tools/${t.id}`) }}>Edit</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
