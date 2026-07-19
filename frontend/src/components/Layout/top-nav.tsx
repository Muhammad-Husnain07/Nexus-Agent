import { Menu, Sun, Moon, Search } from "lucide-react"
import { Input } from "@/components/ui/input"

interface Props { dark: boolean; onToggle: () => void; onMenuClick: () => void }

export default function TopNav({ dark, onToggle, onMenuClick }: Props) {
  return (
    <header className="sticky top-0 z-30 h-14 border-b bg-background/80 backdrop-blur-sm flex items-center gap-4 px-4">
      <button onClick={onMenuClick} className="md:hidden p-2 hover:bg-accent rounded-md">
        <Menu size={20} />
      </button>
      <div className="hidden sm:block relative max-w-sm">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input placeholder="Search..." className="pl-9 h-9" />
      </div>
      <div className="flex-1" />
      <button onClick={onToggle} className="p-2 hover:bg-accent rounded-md text-muted-foreground">
        {dark ? <Sun size={18} /> : <Moon size={18} />}
      </button>
    </header>
  )
}
