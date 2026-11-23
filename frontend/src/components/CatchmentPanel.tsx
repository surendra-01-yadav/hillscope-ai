import { useEffect, useState } from 'react'
import { api, type CatchmentDetail } from '../api'
import { clusterColor, useApp } from '../store'
import { Icon, NatureBadge, fmt } from './ui'

export default function CatchmentPanel() {
  const { selectedCatchment, setSelectedCatchment, regionId, periodId, result } = useApp()
  const [d, setD] = useState<CatchmentDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const runId = result && result.region.id === regionId ? result.run_id : undefined
  const period = result && result.region.id === regionId ? result.period.id : periodId

  useEffect(() => {
    if (!selectedCatchment) { setD(null); return }
    setErr(null)
    api.catchment(selectedCatchment, regionId, period, runId).then(setD).catch(e => setErr(e.message))
  }, [selectedCatchment, regionId, period, runId])

  if (!selectedCatchment) return null
  const f = (k: string) => d?.features.find(x => x.key === k)
  const prof = d?.assignment ? result?.profiles.find(p => p.cluster === d.assignment!.cluster) : undefined
  // Show the features that distinguish this catchment's group, or the most extreme features otherwise.
  const keys = prof ? prof.distinguishing.map(x => x.feature)
    : (d?.features ?? []).slice().sort((a, b) => Math.abs(b.percentile - 0.5) - Math.abs(a.percentile - 0.5)).slice(0, 5).map(x => x.key)
  const key = d?.features.filter(x => keys.includes(x.key)).sort((a, b) => Math.abs(b.percentile - 0.5) - Math.abs(a.percentile - 0.5))[0]

  return (
    <aside className="panel absolute right-4 top-16 z-20 w-[300px] p-3.5" data-testid="catchment-panel">
      <div className="flex items-start justify-between">
        <div>
          <div className="label">Catchment</div>
          <div className="num text-sm font-medium text-white">{selectedCatchment}</div>
          {d?.assignment?.district && <div className="text-[11px] text-ink-400">{d.assignment.district} district</div>}
        </div>
        <button onClick={() => setSelectedCatchment(null)} className="text-ink-400 hover:text-white" aria-label="Close"><Icon name="close" className="h-4 w-4" /></button>
      </div>
      {err && <div className="mt-2 text-xs text-red-300">{err}</div>}
      {d && (
        <>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <Mini label="Area" v={`${fmt(f('area_km2')?.value, 0)} km²`} />
            <Mini label="Elevation" v={`${fmt(f('elev_mean')?.value, 0)} m`} />
            <Mini label="Slope" v={`${fmt(f('slope_mean')?.value, 1)}°`} />
          </div>
          {d.assignment && prof && (
            <div className="mt-3 rounded-lg bg-ink-950/60 p-2.5 ring-1 ring-white/5">
              <div className="flex items-center gap-2">
                <span className="h-3 w-3 rounded-sm" style={{ background: clusterColor(prof.cluster) }} />
                <span className="text-[12.5px] font-semibold">{prof.name}</span>
              </div>
              {d.assignment.probability !== null && (
                <div className="mt-0.5 text-[10.5px] text-ink-400">membership {fmt(d.assignment.probability, 2)}</div>
              )}
            </div>
          )}
          {key && (
            <div className="mt-3 text-[12px] leading-snug text-ink-200">
              <span className="text-ink-400">Key characteristic: </span>
              {key.percentile >= 0.5 ? 'higher' : 'lower'} {key.label.toLowerCase()} than {Math.round((key.percentile >= 0.5 ? key.percentile : 1 - key.percentile) * 100)}% of region
            </div>
          )}
          <div className="mt-3 space-y-1.5">
            {d.features.filter(x => keys.includes(x.key)).slice(0, 5).map(x => (
              <div key={x.key}>
                <div className="flex items-center justify-between text-[11px]">
                  <span className="truncate text-ink-300">{x.label}</span>
                  <span className="num text-ink-200">{fmt(x.value, x.value > 100 ? 0 : 2)} <span className="text-ink-500">{x.unit}</span></span>
                </div>
                <div className="mt-0.5 flex items-center gap-1.5">
                  <div className="relative h-1 flex-1 rounded bg-ink-700">
                    <div className="absolute top-1/2 h-2 w-0.5 -translate-y-1/2 rounded bg-white" style={{ left: `${x.percentile * 100}%` }} />
                  </div>
                  <NatureBadge nature={x.nature} />
                </div>
              </div>
            ))}
          </div>
          {d.recorded_events_concurrent !== undefined && d.recorded_events_concurrent !== null && (
            <div className="mt-3 border-t border-white/5 pt-2 text-[11px] text-ink-400">
              <span className="num text-ink-200">{d.recorded_events_concurrent}</span> district-level flood records in {result?.period.label}
            </div>
          )}
        </>
      )}
      {!d && !err && <div className="mt-3 text-xs text-ink-400">Loading…</div>}
    </aside>
  )
}

function Mini({ label, v }: { label: string; v: string }) {
  return <div><div className="label">{label}</div><div className="num text-[13px] text-ink-100">{v}</div></div>
}
