import { useState } from 'react'
import { useApp } from '../store'
import { Icon, Segmented } from './ui'

export default function LayerControl() {
  const { basemap, setBasemap, hillshade, setHillshade, showGroups, setShowGroups, page, showEvents, setShowEvents } = useApp()
  const [open, setOpen] = useState(false)
  return (
    <div className="absolute right-4 top-4 z-20 flex flex-col items-end">
      <button onClick={() => setOpen(o => !o)} data-testid="layers-button" aria-expanded={open}
        className="panel flex items-center gap-1.5 px-2.5 py-2 text-xs text-ink-200 hover:text-white">
        <Icon name="layers" className="h-4 w-4" /> Layers
      </button>
      {open && (
        <div className="panel mt-2 w-56 space-y-3 p-3" data-testid="layers-panel">
          <div>
            <div className="label mb-1.5">Basemap</div>
            <Segmented size="sm" value={basemap} onChange={setBasemap} options={[{ value: 'dark', label: 'Dark' }, { value: 'satellite', label: 'Satellite' }]} />
          </div>
          <Toggle label="Terrain hillshade" value={hillshade} onChange={setHillshade} />
          <Toggle label="Catchment groups" value={showGroups} onChange={setShowGroups} />
          {page === 'validate' && <Toggle label="Historical events" value={showEvents} onChange={setShowEvents} />}
        </div>
      )}
    </div>
  )
}

function Toggle({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center justify-between text-xs text-ink-200">
      {label}
      <button role="switch" aria-checked={value} onClick={() => onChange(!value)}
        className={`relative h-4 w-7 rounded-full transition ${value ? 'bg-accent' : 'bg-ink-700'}`}>
        <span className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${value ? 'left-3.5' : 'left-0.5'}`} />
      </button>
    </label>
  )
}
