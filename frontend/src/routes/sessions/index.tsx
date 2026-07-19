import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

const sessions = [
  { id: "1", title: "Weather chat", status: "active", messages: 5, date: "2026-07-19" },
  { id: "2", title: "Tool testing", status: "active", messages: 3, date: "2026-07-18" },
]

export default function SessionsPage() {
  return (
    <div className="space-y-6">
      <div><h1 className="text-2xl font-bold tracking-tight">Sessions</h1><p className="text-muted-foreground text-sm">Conversation history</p></div>
      <Card>
        <CardHeader><CardTitle>All Sessions</CardTitle></CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="text-left py-3 px-2 font-medium">Title</th>
                  <th className="text-left py-3 px-2 font-medium">Status</th>
                  <th className="text-left py-3 px-2 font-medium">Messages</th>
                  <th className="text-left py-3 px-2 font-medium">Date</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.id} className="border-b hover:bg-muted/50">
                    <td className="py-3 px-2 font-medium">{s.title}</td>
                    <td className="py-3 px-2"><Badge variant={s.status === "active" ? "success" : "secondary"}>{s.status}</Badge></td>
                    <td className="py-3 px-2 text-muted-foreground">{s.messages}</td>
                    <td className="py-3 px-2 text-muted-foreground">{s.date}</td>
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
