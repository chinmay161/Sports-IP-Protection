// src/App.jsx
import { useState } from "react"

import AlertFeed from "./components/AlertFeed.jsx"
import AssetsPage from "./components/AssetsPage.jsx"
import CasesPage from "./components/CasesPage.jsx"
import DashboardPage from "./components/DashboardPage.jsx"
import DetectionsPage from "./components/DetectionsPage.jsx"
import LookalikePage from "./components/LookalikePage.jsx"
import PropagationPage from "./components/PropagationPage.jsx"
import Sidebar from "./components/Sidebar.jsx"
import SystemPage from "./components/SystemPage.jsx"

const VIEWS = {
  dashboard:   DashboardPage,
  alerts:      AlertFeed,
  assets:      AssetsPage,
  cases:       CasesPage,
  detections:  DetectionsPage,
  lookalike:   LookalikePage,
  propagation: PropagationPage,
  system:      SystemPage,
}

export default function App() {
  const [view, setView] = useState("dashboard")
  const [preselectedMatchId, setPreselectedMatchId] = useState(null)
  const Current = VIEWS[view] ?? DashboardPage

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100">
      <Sidebar active={view} onSelect={setView} />
      <main className="flex-1 overflow-hidden">
        <Current
          onNavigate={setView}
          onSelectMatch={setPreselectedMatchId}
          preselectedMatchId={preselectedMatchId}
        />
      </main>
    </div>
  )
}