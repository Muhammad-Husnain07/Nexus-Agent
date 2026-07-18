import EmbeddedWidget from '@/features/embed/EmbeddedWidget'
import { createRoot } from 'react-dom/client'

const rootEl = document.getElementById('nexus-embed-root')
if (rootEl) {
  const root = createRoot(rootEl)
  root.render(<EmbeddedWidget />)
}

export default EmbeddedWidget
