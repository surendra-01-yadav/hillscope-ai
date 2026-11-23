import { useEffect, useState } from 'react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, type Association } from '../api'
import { BAND_COLORS } from '../components/MapView'
import { Button, Segmented, fmt } from '../components/ui'
import { clusterColor, useApp } from '../store'

type Props = { mode: 'clusters' | 'baseline'; setMode: (m: 'clusters' | 'baseline') => void; onEventPoints: (fc: GeoJSON.FeatureCollection | null) => void }

export default function Validate({ mode, setMode, onEventPoints }: Props) {
  const { result, regionId, setPage, setShowEvents } = useApp()
  const [win, setWin] = useState<'concurrent' | 'out_of_period'>('concurrent')
  const [etype, setEtype] = useState<'all' | 'flash'>('all')
  const [open, setOpen] = useState(false)
  const hasRun = !!result && result.region.id === regionId
  const w = hasRun ? result.validation.windows[win] : undefined

  useEffect(() => { setShowEvents(true) }, [setShowEvents])
  useEffect(() => {
    if (!w) { onEventPoints(null); return }
    api.districtEvents(regionId, w.years[0], w.years[1], etype === 'flash').then(onEventPoints).catch(() => onEventPoints(null))
  }, [regionId, w?.years[0], w?.years[1], etype]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!hasRun) {
    return (
      <section className="panel absolute left-4 top-4 z-10 w-[352px] p-4">
        <h2 className="text-[15px] font-semibold text-white">Historical validation</h2>
        <p className="mt-2 text-[12px] text-ink-400">Run a discovery first — validation compares discovered groups with independently recorded flood events.</p>
        <Button className="mt-3 w-full" onClick={() => setPage('discover')}>Go to Discover</Button>
      </section>
    )
  }
  const d = w ? w[etype] : undefined
  const ce = d?.clusters.epsilon_squared ?? null
  const be = d?.baseline.epsilon_squared ?? null
  const verdict = ce === null || be === null ? 'not comparable' : ce > be * 1.1 ? 'stronger than baseline' : ce < be * 0.9 ? 'weaker than baseline' : 'similar to baseline'
  const chart = d ? [
    ...d.clusters.groups.map(g => ({ name: g.group < 0 ? 'N' : String(g.group), full: g.name, v: g.events_per_catchment_year, c: clusterColor(g.group) })),
    { name: '', full: '', v: 0, c: 'transparent' },
    ...d.baseline.groups.map(g => ({ name: g.name.split(' ')[0].slice(0, 3), full: `Baseline: ${g.name}`, v: g.events_per_catchment_year, c: BAND_COLORS[g.group] })),
  ] : []

  return (
    <section className="panel scroll-thin absolute left-4 top-4 z-10 max-h-[calc(100%-2rem)] w-[352px] overflow-y-auto p-4" data-testid="validate-panel">
      <h2 className="text-[15px] font-semibold text-white">Historical validation</h2>
      <p className="mt-1 text-[11.5px] text-ink-400">Independent flood records (IMD-based India Flood Inventory) — never used for clustering.</p>
      <div className="mt-3 space-y-2">
        <Segmented size="sm" value={win} onChange={setWin} testId="window-select" options={Object.entries(result.validation.windows).map(([k, v]) => ({
          value: k as 'concurrent' | 'out_of_period', label: `${k === 'concurrent' ? 'Same period' : 'Later'} ${v.years[0]}–${v.years[1]}` }))} />
        <Segmented size="sm" value={etype} onChange={setEtype} testId="event-type" options={[{ value: 'all', label: 'All floods' }, { value: 'flash', label: 'Flash / cloudburst' }]} />
        <Segmented size="sm" value={mode} onChange={setMode} testId="map-mode" options={[{ value: 'clusters', label: 'Map: groups' }, { value: 'baseline', label: 'Map: elevation bands' }]} />
      </div>
      {d && (
        <>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <Big label="Discovered groups" v={fmt(ce, 3)} accent />
            <Big label="Elevation baseline" v={fmt(be, 3)} />
          </div>
          <p className="mt-1.5 text-[11px] text-ink-400">Event-association strength (Kruskal–Wallis ε²): <span className="text-ink-100">{verdict}</span>.</p>
          <div className="label mb-1 mt-4">Recorded events per catchment · year</div>
          <div className="h-[150px]" data-testid="assoc-chart">
            <ResponsiveContainer>
              <BarChart data={chart} margin={{ left: -22, right: 0, top: 4, bottom: 0 }}>
                <XAxis dataKey="name" stroke="#5b6b7b" fontSize={10} tickLine={false} interval={0} />
                <YAxis stroke="#5b6b7b" fontSize={10} tickLine={false} tickFormatter={v => fmt(v, 2)} />
                <Tooltip contentStyle={{ background: '#0d1318', border: '1px solid #243241', fontSize: 11 }} labelFormatter={(_, p) => p?.[0]?.payload?.full}
                  formatter={(v) => [fmt(Number(v), 3), 'events / catchment / yr']} />
                <Bar isAnimationActive={false} dataKey="v" radius={2}>{chart.map((c, i) => <Cell key={i} fill={c.c} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            <Small label="Events" v={d.n_events} />
            <Small label="Matched" v={d.n_events_matched} />
            <Small label="Coverage" v={`${Math.round(d.spatial_coverage * 100)}%`} />
          </div>
          <button onClick={() => setOpen(o => !o)} className="mt-4 w-full rounded-lg bg-ink-800 px-3 py-2 text-left text-[11.5px] text-ink-200 hover:bg-ink-700" data-testid="methodology-toggle">
            {open ? '▾' : '▸'} Methodology &amp; detailed metrics
          </button>
          {open && (
            <div className="mt-2 space-y-3 text-[11px]" data-testid="methodology">
              <AssocTable title="Discovered groups" a={d.clusters} colors={g => clusterColor(g)} />
              <AssocTable title="Elevation tertiles" a={d.baseline} colors={g => BAND_COLORS[g]} />
              <p className="text-ink-400">Same-k elevation bands ε² = <span className="num text-ink-200">{fmt(d.baseline_same_k.epsilon_squared, 3)}</span> (controls for number of groups).</p>
              <ul className="list-disc space-y-1 pl-4 text-ink-400">{result.validation.notes.map(n => <li key={n}>{n}</li>)}</ul>
            </div>
          )}
        </>
      )}
    </section>
  )
}

function AssocTable({ title, a, colors }: { title: string; a: Association; colors: (g: number) => string }) {
  return (
    <div>
      <div className="label mb-1">{title} · H={fmt(a.kruskal_H, 1)} · p={a.kruskal_p === null ? '–' : a.kruskal_p.toExponential(1)}</div>
      <table className="w-full">
        <thead><tr className="text-left text-ink-500"><th className="font-medium">Group</th><th className="font-medium">n</th><th className="font-medium">Events</th><th className="font-medium">Rate</th><th className="font-medium">Lift</th></tr></thead>
        <tbody className="num text-ink-200">
          {a.groups.map(g => (
            <tr key={g.group}>
              <td className="py-0.5 font-sans"><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: colors(g.group) }} />{g.name}</td>
              <td>{g.n_catchments}</td><td>{g.n_events}</td><td>{fmt(g.association_rate, 2)}</td><td>{fmt(g.lift, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Big({ label, v, accent }: { label: string; v: string; accent?: boolean }) {
  return <div className="rounded-lg bg-ink-950/60 p-2.5 ring-1 ring-white/5"><div className="label">{label}</div><div className={`num text-xl ${accent ? 'text-accent' : 'text-ink-100'}`}>{v}</div></div>
}
function Small({ label, v }: { label: string; v: string | number }) {
  return <div><div className="label">{label}</div><div className="num text-[13px]">{v}</div></div>
}
