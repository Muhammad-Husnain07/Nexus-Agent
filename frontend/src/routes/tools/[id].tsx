import { useParams, useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

export default function ToolDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold tracking-tight">{id ? `Tool ${id.slice(0, 8)}` : "Tool"}</h1></div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => navigate("/test")}>Test</Button>
          <Button>Edit</Button>
        </div>
      </div>
      <div className="grid gap-6 grid-cols-1 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Description</CardTitle></CardHeader>
          <CardContent><p className="text-muted-foreground">Tool description goes here.</p></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Details</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div><span className="text-xs text-muted-foreground">Category</span><Badge variant="outline" className="ml-2">data</Badge></div>
            <div><span className="text-xs text-muted-foreground">Risk</span><Badge variant="success" className="ml-2">low</Badge></div>
            <div><span className="text-xs text-muted-foreground">Endpoint</span><p className="text-sm mt-1">https://api.example.com</p></div>
            <div><span className="text-xs text-muted-foreground">Method</span><Badge variant="default" className="ml-2">GET</Badge></div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
