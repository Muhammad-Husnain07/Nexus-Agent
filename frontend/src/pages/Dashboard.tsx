export default function Dashboard() {
  return (
    <div className="p-8">
      <h1 className="text-3xl font-bold mb-4">Nexus Agent Platform</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <a href="/tools/new" className="border rounded-lg p-6 hover:shadow-md transition-shadow">
          <h2 className="text-xl font-semibold mb-2">Tool Builder</h2>
          <p className="text-muted-foreground">Create and register new tools</p>
        </a>
        <a href="/test" className="border rounded-lg p-6 hover:shadow-md transition-shadow">
          <h2 className="text-xl font-semibold mb-2">Test Playground</h2>
          <p className="text-muted-foreground">Test your registered tools</p>
        </a>
        <a href="/chat" className="border rounded-lg p-6 hover:shadow-md transition-shadow">
          <h2 className="text-xl font-semibold mb-2">Chat</h2>
          <p className="text-muted-foreground">Conversation interface with tool integration</p>
        </a>
        <a href="/embed" className="border rounded-lg p-6 hover:shadow-md transition-shadow">
          <h2 className="text-xl font-semibold mb-2">Embed Widget</h2>
          <p className="text-muted-foreground">Generate embeddable chat widget</p>
        </a>
      </div>
    </div>
  )
}
