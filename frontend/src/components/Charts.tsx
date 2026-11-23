import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts'
import type { RunResult } from '../api'
import { clusterColor } from '../store'
import { fmt } from './ui'

const axis = { stroke: '#5b6b7b', fontSize: 10, tickLine: false }
const tip = { contentStyle: { background: '#0d1318', border: '1px solid #243241', borderRadius: 8, fontSize: 11 }, itemStyle: { color: '#e7ecf0' }, labelStyle: { color: '#a9b5c1' } }

/** Side-by-side comparison of two clusters' feature profiles (robust z vs regional median). */
export function ClusterCompare({ result, a, b }: { result: RunResult; a: number | null; b: number | null }) {
  const pa = result.profiles.find(p => p.cluster === a)
  const pb = result.profiles.find(p => p.cluster === b)
  if (!pa) return <p className="text-[11.5px] text-ink-400">Select a group to see what makes it different. Select a second to compare.</p>
  const keys = Array.from(new Set([...pa.distinguishing.map(d => d.feature), ...(pb?.distinguishing.map(d => d.feature) ?? [])])).slice(0, 8)
  const label = (k: string) => result.features.find(f => f.key === k)?.label ?? k
  const data = keys.map(k => ({ k: label(k), a: pa.z_profile[k] ?? 0, b: pb ? pb.z_profile[k] ?? 0 : undefined }))
  return (
    <div data-testid="cluster-compare">
      <p className="mb-2 text-[11.5px] leading-snug text-ink-300"><span className="font-semibold" style={{ color: clusterColor(pa.cluster) }}>{pa.name}.</span> {pa.summary}</p>
      {pb && <p className="mb-2 text-[11.5px] leading-snug text-ink-300"><span className="font-semibold" style={{ color: clusterColor(pb.cluster) }}>{pb.name}.</span> {pb.summary}</p>}
      <div style={{ height: 26 * data.length + 30 }}>
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ left: 0, right: 8, top: 0, bottom: 0 }} barGap={1}>
            <CartesianGrid horizontal={false} stroke="#1c2731" />
            <XAxis type="number" {...axis} domain={['dataMin', 'dataMax']} tickFormatter={v => fmt(v, 1)} />
            <YAxis type="category" dataKey="k" width={118} {...axis} tick={{ fill: '#a9b5c1', fontSize: 10 }} />
            <ReferenceLine x={0} stroke="#8393a3" />
            <Tooltip {...tip} formatter={(v) => fmt(Number(v), 2)} />
            <Bar isAnimationActive={false} dataKey="a" name={pa.name} fill={clusterColor(pa.cluster)} barSize={pb ? 7 : 11} radius={2} />
            {pb && <Bar isAnimationActive={false} dataKey="b" name={pb.name} fill={clusterColor(pb.cluster)} barSize={7} radius={2} />}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-[10px] text-ink-500">Bars: group median minus regional median, in IQR units. Proxies marked “estimated” are not measured discharge.</p>
    </div>
  )
}

export function PcaScatter({ result, highlight }: { result: RunResult; highlight: (number | null)[] }) {
  const focus = highlight.filter((h): h is number => h !== null)
  const groups = Array.from(new Set(result.assignments.map(a => a.cluster))).sort((x, y) => x - y)
  const ev = result.pca.explained_variance
  return (
    <div data-testid="pca-view">
      <div className="h-[220px]">
        <ResponsiveContainer>
          <ScatterChart margin={{ left: -18, right: 6, top: 4, bottom: 0 }}>
            <CartesianGrid stroke="#1c2731" />
            <XAxis type="number" dataKey="x" {...axis} name={`PC1`} tickFormatter={v => fmt(v, 0)} />
            <YAxis type="number" dataKey="y" {...axis} name={`PC2`} tickFormatter={v => fmt(v, 0)} />
            <ZAxis range={[14, 14]} />
            <Tooltip {...tip} cursor={false} formatter={(v) => fmt(Number(v), 2)} />
            {groups.map(g => (
              <Scatter isAnimationActive={false} key={g} name={String(g)} data={result.assignments.filter(a => a.cluster === g).map(a => ({ x: a.pca[0], y: a.pca[1] ?? 0, id: a.catchment_id }))}
                fill={clusterColor(g)} fillOpacity={focus.length && !focus.includes(g) ? 0.12 : 0.85} />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[10px] leading-snug text-ink-500">
        Dimensionality-reduction view: PC1 {fmt(ev[0] * 100, 0)}% + PC2 {fmt((ev[1] ?? 0) * 100, 0)}% of variance. Distances are in feature space, not geographic.
      </p>
    </div>
  )
}

export function ModelTable({ result }: { result: RunResult }) {
  const sweep = result.sweep.filter(s => s.metrics.silhouette !== null)
  const sweepData = sweep.map(s => ({ k: s.metrics.n_clusters, label: Object.values(s.params).slice(0, 2).join('/'), sil: s.metrics.silhouette, st: s.metrics.stability, sel: s.metrics.selection_score }))
  return (
    <div data-testid="model-table">
      <table className="w-full text-[11px]">
        <thead><tr className="text-left text-ink-400"><th className="pb-1 font-medium">Model</th><th className="font-medium">k</th><th className="font-medium">Silh.</th><th className="font-medium">DB</th><th className="font-medium">Stab.</th></tr></thead>
        <tbody className="num">
          {result.comparison.map(c => (
            <tr key={c.algorithm} className={c.algorithm === result.algorithm ? 'text-white' : 'text-ink-300'}>
              <td className="py-0.5 font-sans">{c.name.replace('Hierarchical (Ward)', 'Ward').replace('Gaussian Mixture', 'GMM')}{c.algorithm === result.recommended_algorithm && <span className="ml-1 text-accent" title="Most defensible by internal criteria">★</span>}</td>
              <td>{c.metrics.n_clusters}{c.metrics.n_noise ? <span className="text-ink-500">+n</span> : ''}</td>
              <td>{fmt(c.metrics.silhouette, 2)}</td><td>{fmt(c.metrics.davies_bouldin, 2)}</td><td>{fmt(c.metrics.stability, 2)}</td>
            </tr>
          ))}
          <tr className="border-t border-white/5 text-ink-400"><td className="py-0.5 font-sans">Elevation bands</td><td>3</td><td>{fmt(result.baseline.metrics.silhouette, 2)}</td><td>{fmt(result.baseline.metrics.davies_bouldin, 2)}</td><td>–</td></tr>
        </tbody>
      </table>
      <div className="label mb-1 mt-3">{result.algorithm_name} sweep — silhouette & stability</div>
      <div className="h-[110px]">
        <ResponsiveContainer>
          <BarChart data={sweepData} margin={{ left: -24, right: 0, top: 2, bottom: 0 }}>
            <XAxis dataKey="label" {...axis} interval={0} tick={{ fill: '#8393a3', fontSize: 9 }} />
            <YAxis {...axis} domain={[0, 1]} />
            <Tooltip {...tip} formatter={(v) => fmt(Number(v), 3)} />
            <Bar isAnimationActive={false} dataKey="sil" name="silhouette" radius={2}>
              {sweepData.map((_, i) => <Cell key={i} fill={JSON.stringify(sweep[i].params) === JSON.stringify(result.selected.params) ? '#3ec5b4' : '#344556'} />)}
            </Bar>
            <Bar isAnimationActive={false} dataKey="st" name="stability (ARI)" fill="#5b6b7b" radius={2} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-[10px] leading-snug text-ink-500">Selection uses silhouette, Davies–Bouldin, bootstrap stability and size balance — never historical events.</p>
    </div>
  )
}

/** Truncated Ward dendrogram (scipy coordinates rendered as SVG). */
export function Dendrogram({ result }: { result: RunResult }) {
  const d = result.dendrogram
  if (!d) return null
  const W = 320, H = 130, pad = 4
  const xs = d.icoord.flat(), maxX = Math.max(...xs), minX = Math.min(...xs)
  const sx = (x: number) => pad + ((x - minX) / (maxX - minX || 1)) * (W - 2 * pad)
  const sy = (y: number) => H - pad - (y / (d.max_height || 1)) * (H - 2 * pad)
  // horizontal cut line between the k-th and (k-1)-th highest merges
  const heights = d.dcoord.map(c => Math.max(...c)).sort((a, b) => b - a)
  const k = result.selected.metrics.n_clusters
  const cut = k > 1 && heights.length >= k ? (heights[k - 2] + heights[k - 1]) / 2 : null
  return (
    <div data-testid="dendrogram">
      <div className="label mb-1 mt-3">Ward dendrogram (top {d.leaves.length} merges)</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        {d.icoord.map((ic, i) => (
          <polyline key={i} fill="none" stroke="#8393a3" strokeWidth={1}
            points={ic.map((x, j) => `${sx(x)},${sy(d.dcoord[i][j])}`).join(' ')} />
        ))}
        {cut !== null && <line x1={0} x2={W} y1={sy(cut)} y2={sy(cut)} stroke="#3ec5b4" strokeDasharray="4 3" />}
      </svg>
      <p className="text-[10px] text-ink-500">Dashed line: cut producing {k} groups. Height = Ward merge distance.</p>
    </div>
  )
}

const DIST_KEYS: [string, string, string][] = [
  ['rain_annual', 'Annual rainfall', 'mm'], ['rx1day', 'Max 1-day rain', 'mm'], ['rx3day', 'Max 3-day rain', 'mm'],
  ['slope_mean', 'Mean slope', '°'], ['elev_mean', 'Elevation', 'm'], ['tc_kirpich_h', 'Tc (estimated)', 'h'],
]

/** Interquartile range (bar) and median (tick) of key rainfall/terrain features for every group. */
export function DistributionStrips({ result, focus }: { result: RunResult; focus: (number | null)[] }) {
  const f = focus.filter((x): x is number => x !== null)
  const profs = result.profiles
  return (
    <div className="mt-4 space-y-2.5" data-testid="distributions">
      <div className="label">Distributions by group (P25–P75, median)</div>
      {DIST_KEYS.filter(([k]) => profs.some(p => p.stats[k])).map(([k, label, unit]) => {
        const vals = profs.flatMap(p => [p.stats[k]?.p25, p.stats[k]?.p75]).filter((v): v is number => v !== null && v !== undefined)
        const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1
        const pos = (v: number) => `${((v - lo) / span) * 100}%`
        return (
          <div key={k}>
            <div className="flex justify-between text-[10.5px] text-ink-400"><span>{label}</span><span className="num">{fmt(lo, lo > 100 ? 0 : 1)}–{fmt(hi, hi > 100 ? 0 : 1)} {unit}</span></div>
            <div className="relative mt-0.5" style={{ height: 4 * profs.length + 2 }}>
              {profs.map((p, i) => {
                const s = p.stats[k]
                if (!s || s.p25 === null || s.p75 === null || s.median === null) return null
                const dim = f.length > 0 && !f.includes(p.cluster)
                return (
                  <div key={p.cluster} className="absolute h-[3px] rounded-full" title={`${p.name}: median ${fmt(s.median, 1)} ${unit}`}
                    style={{ top: i * 4, left: pos(s.p25), width: `calc(${pos(s.p75)} - ${pos(s.p25)} + 2px)`, background: clusterColor(p.cluster), opacity: dim ? 0.15 : 0.9 }}>
                    <span className="absolute -top-[2px] h-[7px] w-[2px] bg-white" style={{ left: `calc(${((s.median - s.p25) / ((s.p75 - s.p25) || 1)) * 100}% - 1px)`, opacity: dim ? 0.2 : 1 }} />
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
