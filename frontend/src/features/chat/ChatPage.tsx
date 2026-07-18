import { useParams } from "react-router-dom"
import ChatView from "./ChatView"

export default function ChatPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  return <ChatView sessionId={sessionId ?? null} />
}
