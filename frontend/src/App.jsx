// src/App.jsx
import AlertFeed from "./components/AlertFeed.jsx"
import Sidebar from "./components/Sidebar.jsx"

export default function App() {
  return (
    <div className="flex h-screen bg-slate-950 text-slate-100">
      <Sidebar />
      <main className="flex-1 overflow-hidden">
        <AlertFeed />
      </main>
    </div>
  )
}