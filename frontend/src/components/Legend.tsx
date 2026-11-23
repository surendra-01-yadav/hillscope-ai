import { clusterColor, useApp } from '../store'
import { BAND_COLORS, ELEV_STOPS, type ColorMode } from './MapView'

export default function Legend({ mode }: { mode: ColorMode }) {
  const { result, selectedCluster, setSelectedCluster, page } = useApp()
  if (page === 'discover' && mode === 'clusters') return null // the Discover panel lists groups itself
  return (
    <div className={`panel absolute bottom-4 z-10 max-w-[280px] px-3 py-2.5 ${page === 'explore' ? 'left-4' : 'left-[380px]'}`} data-testid="legend">
      {mode === 'elevation' && (
        <>
          <div className="label mb-1.5">Mean catchment elevation</div>
          <div className="h-2 w-52 rounded-sm" style={{ background: `linear-gradient(90deg, ${ELEV_STOPS.map(s => s[1]).join(',')})` }} />
          <div className="num mt-1 flex w-52 justify-between text-[10px] text-ink-400"><span>500 m</span><span>3000</span><span>5500 m</span></div>
        </>
      )}
      {mode === 'clusters' && result && (
        <>
          <div className="label mb-1">Behavioural groups · {result.algorithm_name}</div>
          {result.profiles.map(p => (
            <button key={p.cluster} onClick={() => setSelectedCluster(selectedCluster === p.cluster ? null : p.cluster)}
              className={`flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-[11.5px] ${selectedCluster === p.cluster ? 'bg-ink-700' : 'hover:bg-ink-800'}`}>
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: clusterColor(p.cluster) }} />
              <span className="flex-1 truncate">{p.name}</span>
              <span className="num text-ink-400">{p.n_catchments}</span>
            </button>
          ))}
        </>
      )}
      {mode === 'baseline' && result && (
        <>
          <div className="label mb-1">Elevation-band baseline</div>
          {result.baseline.bands.map(b => (
            <div key={b.band} className="flex items-center gap-2 text-[11.5px]">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: BAND_COLORS[b.band] }} />
              <span className="flex-1">{b.name}</span>
              <span className="num text-ink-400">{Math.round(b.min_m)}–{Math.round(b.max_m)} m</span>
            </div>
          ))}
        </>
      )}
    </div>
  )
}
