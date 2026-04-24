// src/components/Sidebar.jsx
const NAV = [
  { id: "dashboard", label: "Dashboard", icon: "▦", disabled: true },
  { id: "assets", label: "Assets", icon: "◆", disabled: true },
  { id: "alerts", label: "Alerts", icon: "!", disabled: false },
  { id: "cases", label: "Cases", icon: "⬢", disabled: true },
  { id: "settings", label: "Settings", icon: "⚙", disabled: true },
]

export default function Sidebar() {
  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-950/80">
      <div className="px-5 py-5">
        <div className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
          Sports IP
        </div>
        <div className="text-lg font-bold text-slate-100">Protection</div>
      </div>

      <nav className="flex-1 px-2">
        {NAV.map((item) => (
          <button
            key={item.id}
            disabled={item.disabled}
            className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition ${
              item.disabled
                ? "cursor-not-allowed text-slate-600"
                : "bg-slate-800/60 font-medium text-slate-100"
            }`}
          >
            <span className="w-4 text-center">{item.icon}</span>
            <span>{item.label}</span>
            {item.disabled && (
              <span className="ml-auto text-[10px] uppercase tracking-wider text-slate-700">
                soon
              </span>
            )}
          </button>
        ))}
      </nav>

      <div className="border-t border-slate-800 px-5 py-4 text-xs text-slate-500">
        <div>Dev mode</div>
        <div className="text-[10px]">AUTH_DISABLED=true</div>
      </div>
    </aside>
  )
}