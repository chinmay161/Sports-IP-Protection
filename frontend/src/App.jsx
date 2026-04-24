// src/App.jsx
import { useState } from "react"

import AlertFeed from "./components/AlertFeed.jsx"
import AssetsPage from "./components/AssetsPage.jsx"
import Sidebar from "./components/Sidebar.jsx"

export default function App() {
  const [view, setView] = useState("alerts")

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100">
      <Sidebar active={view} onSelect={setView} />
      <main className="flex-1 overflow-hidden">
        {view === "assets" ? <AssetsPage /> : <AlertFeed />}
      </main>
    </div>
  )
}