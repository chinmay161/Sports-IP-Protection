// src/App.jsx
import { useState } from "react"

import AlertFeed from "./components/AlertFeed.jsx"
import AssetsPage from "./components/AssetsPage.jsx"
import PropagationPage from "./components/PropagationPage.jsx"
import Sidebar from "./components/Sidebar.jsx"

const VIEWS = {
  alerts: AlertFeed,
  assets: AssetsPage,
  propagation: PropagationPage,
}

export default function App() {
  const [view, setView] = useState("alerts")
  const Current = VIEWS[view] ?? AlertFeed

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100">
      <Sidebar active={view} onSelect={setView} />
      <main className="flex-1 overflow-hidden">
        <Current />
      </main>
    </div>
  )
}