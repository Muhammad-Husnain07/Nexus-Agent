import { useState } from "react"
import { Outlet } from "react-router-dom"
import Sidebar from "@/components/layout/sidebar"
import TopNav from "@/components/layout/top-nav"

interface Props { dark: boolean; onToggle: () => void }

export default function DashboardLayout({ dark, onToggle }: Props) {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="flex min-h-screen">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex-1 flex flex-col min-w-0">
        <TopNav dark={dark} onToggle={onToggle} onMenuClick={() => setSidebarOpen(!sidebarOpen)} />
        <main className="flex-1 p-4 md:p-6 space-y-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
