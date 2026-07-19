import { useParams } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export default function SessionDetailPage() {
  const { id } = useParams()
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Session: {id?.slice(0, 8)}</h1>
      <Card><CardContent className="p-6 text-muted-foreground">Conversation transcript will appear here.</CardContent></Card>
    </div>
  )
}
