import { useMemo, useState } from 'react'
import MapView, { type ColorMode } from './components/MapView'
import { Icon } from './components/ui'
import { useApp, type Page } from './store'
import Explore from './pages/Explore'
import Discover from './pages/Discover'
import Validate from './pages/Validate'
import Reports from './pages/Reports'
import CatchmentPanel from './components/CatchmentPanel'
import Legend from './components/Legend'
import LayerControl from './components/LayerControl'
import DemoGuide from './components/DemoGuide'

const NAV: { id: Page; label: string; icon: 'explore' | 'discover' | 'validate' | 'reports' }[] = [
  { id: 'explore', label: 'Explore', icon: 'explore' },
  { id: 'discover', label: 'Discover', icon: 'discover' },
  { id: 'validate', label: 'Validate', icon: 'validate' },
  { id: 'reports', label: 'Reports', icon: 'reports' },
]

export default function App() {
  const { page, setPage, result, regionId, bootError } = useApp()
  const [validationMode, setValidationMode] = useState<'clusters' | 'baseline'>('clusters')
  const [eventPoints, setEventPoints] = useState<GeoJSON.FeatureCollection | null>(null)
  const [demo, setDemo] = useState(false)
  const hasRun = !!result && result.region.id === regionId

  const colorMode: ColorMode = useMemo(() => {
    if (!hasRun) return 'elevation'
    if (page === 'validate') return validationMode
    return 'clusters'
  }, [hasRun, page, validationMode])

  return (
    <div className="relative flex h-full w-full overflow-hidden">
      <nav className="z-20 flex w-[68px] shrink-0 flex-col items-center border-r border-white/5 bg-ink-950 py-3" aria-label="Primary">
        <div className="mb-5 flex flex-col items-center" title="HillScope AI">
          <img src="/favicon.svg" alt="" className="h-8 w-8" />
          <div className="mt-1 text-[9px] font-bold tracking-[0.14em] text-ink-300">HILLSCOPE</div>
        </div>
        {NAV.map(n => (
          <button key={n.id} onClick={() => setPage(n.id)} data-testid={`nav-${n.id}`} aria-current={page === n.id ? 'page' : undefined}
            className={`mb-1 flex w-[56px] flex-col items-center gap-1 rounded-lg py-2 text-[10px] font-medium transition ${
              page === n.id ? 'bg-ink-800 text-accent' : 'text-ink-400 hover:bg-ink-900 hover:text-ink-200'}`}>
            <Icon name={n.icon} />
            {n.label}
          </button>
        ))}
        <div className="flex-1" />
        <button onClick={() => setDemo(d => !d)} data-testid="demo-toggle"
          className={`flex w-[56px] flex-col items-center gap-1 rounded-lg py-2 text-[10px] font-medium ${demo ? 'text-warn' : 'text-ink-400 hover:text-ink-200'}`}>
          <Icon name="play" />
          Demo
        </button>
      </nav>

      <main className="relative flex-1">
        <MapView colorMode={colorMode} eventPoints={page === 'validate' ? eventPoints : null} />
        {bootError && (
          <div className="panel absolute left-1/2 top-6 z-30 -translate-x-1/2 px-4 py-3 text-sm text-red-200">{bootError}. Start the API with <code className="num">uvicorn app.main:app</code>.</div>
        )}
        {page === 'explore' && <Explore />}
        {page === 'discover' && <Discover />}
        {page === 'validate' && <Validate mode={validationMode} setMode={setValidationMode} onEventPoints={setEventPoints} />}
        {page === 'reports' && <Reports />}
        {page !== 'reports' && <CatchmentPanel />}
        {page !== 'reports' && <Legend mode={colorMode} />}
        {page !== 'reports' && <LayerControl />}
        {demo && <DemoGuide onClose={() => setDemo(false)} />}
      </main>
    </div>
  )
}
