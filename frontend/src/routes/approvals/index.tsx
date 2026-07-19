import { useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

const pending = [
  { id: "1", tool: "open_meteo_forecast", risk: "low", status: "pending", date: "2026-07-19" },
  { id: "2", tool: "delete_file", risk: "high", status: "pending", date: "2026-07-18" },
]

export default function ApprovalsPage() {
  const [tab, setTab] = useState<"pending" | "history">("pending")

  return (
    <div className="space-y-6">
      <div><h1 className="text-2xl font-bold tracking-tight">Approvals</h1></div>
      <div className="flex gap-2 border-b">
        <button className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${tab === "pending" ? "border-primary text-foreground" : "border-transparent text-muted-foreground"}`} onClick={() => setTab("pending")}>Pending</button>
        <button className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${tab === "history" ? "border-primary text-foreground" : "border-transparent text-muted-foreground"}`} onClick={() => setTab("history")}>History</button>
      </div>
      <Card><CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b text-muted-foreground">
              <th className="text-left py-3 px-4 font-medium">Tool</th>
              <th className="text-left py-3 px-4 font-medium">Risk</th>
              <th className="text-left py-3 px-4 font-medium">Status</th>
              <th className="text-left py-3 px-4 font-medium">Date</th>
              <th className="text-right py-3 px-4 font-medium">Actions</th>
            </tr></thead>
            <tbody>
              {pending.map((a) => (
                <tr key={a.id} className="border-b hover:bg-muted/50">
                  <td className="py-3 px-4">{a.tool}</td>
                  <td className="py-3 px-4"><Badge variant={a.risk === "high" ? "destructive" : "success"}>{a.risk}</Badge></td>
                  <td className="py-3 px-4"><Badge variant="outline">{a.status}</Badge></td>
                  <td className="py-3 px-4 text-muted-foreground">{a.date}</td>
                  <td className="py-3 px-4 text-right"><div className="flex gap-1 justify-end"><Button size="sm" variant="outline" className="text-green-600">Approve</Button><Button size="sm" variant="outline" className="text-red-600">Reject</Button></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent></Card>
    </div>
  )
}
