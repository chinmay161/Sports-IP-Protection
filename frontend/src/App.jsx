function App() {
  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <section className="mx-auto flex min-h-screen w-full max-w-3xl flex-col items-center justify-center gap-6 px-6 text-center">
        <span className="inline-flex rounded-full border border-cyan-400/40 bg-cyan-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-200">
          Vite + React + Tailwind CSS
        </span>

        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Frontend is initialized
        </h1>

        <p className="max-w-xl text-base text-slate-300 sm:text-lg">
          Start building your Sports IP Protection UI in
          <code className="mx-1 rounded bg-slate-800 px-2 py-1 text-cyan-200">
            src/App.jsx
          </code>
        </p>

        <div className="flex flex-wrap items-center justify-center gap-3">
          <a
            href="https://tailwindcss.com/docs/installation/using-vite"
            target="_blank"
            rel="noreferrer"
            className="rounded-lg bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300"
          >
            Tailwind Docs
          </a>
          <a
            href="https://vite.dev/guide/"
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-100 transition hover:border-slate-500"
          >
            Vite Guide
          </a>
        </div>
      </section>
    </main>
  )
}

export default App
