import { useEffect, useState } from 'react'
import { useApp } from '../store'
import { Button, Icon } from './ui'

type Step = { title: string; body: string; run?: () => void; ready?: () => boolean; cta?: string }

/** Guided walkthrough. It drives the real UI; the clustering step triggers the actual backend pipeline. */
export default function DemoGuide({ onClose }: { onClose: () => void }) {
  const app = useApp()
  const [i, setI] = useState(0)
  const hasRun = !!app.result && app.result.region.id === app.regionId
  // Prefer the 20-year period, but only use periods whose rainfall is already cached locally.
  const cachedP = app.regions.find(r => r.id === 'uttarakhand')?.periods_cached ?? []
  const demoPeriod = cachedP.includes('2001-2020') ? '2001-2020' : (cachedP[0] ?? '2001-2020')
  const rapid = () => {
    const ps = app.result?.profiles.filter(p => p.cluster >= 0) ?? []
    const score = (p: (typeof ps)[number]) => (p.z_profile.flashiness_proxy ?? 0) + (p.z_profile.melton ?? 0) + (p.z_profile.slope_mean ?? 0)
    return ps.slice().sort((a, b) => score(b) - score(a))
  }
  const steps: Step[] = [
    { title: 'A real hill region', body: 'Uttarakhand Himalaya: HydroBASINS level-12 catchments, coloured by mean elevation from the Copernicus DEM.',
      run: () => { app.setPage('explore'); app.setRegionId('uttarakhand'); app.setSelectedCatchment(null) } },
    { title: 'Set up the discovery', body: `CHIRPS daily rainfall for ${demoPeriod.replace('-', '–')}, the full behavioural feature set, and K-Means.`,
      run: () => { app.setPage('discover'); app.setPeriodId(demoPeriod); app.setFeatureSet('behavioural'); app.setAlgorithm('kmeans') } },
    { title: 'Discover groups', body: 'This runs the real backend pipeline. Each stage you see is reported by the server as it computes.',
      cta: 'Run discovery', run: () => (document.querySelector('[data-testid=discover-button]') as HTMLButtonElement | null)?.click(), ready: () => hasRun },
    { title: 'Why do these catchments group?', body: 'The highlighted group is the one with the steepest, most rapid-response terrain proxies. Its bars show how it differs from the region.',
      run: () => { app.setPage('discover'); app.setCompareCluster(null); app.setSelectedCluster(rapid()[0]?.cluster ?? 0) } },
    { title: 'Compare two behaviours', body: 'Contrast it with the group at the other end of the response spectrum.',
      run: () => { const r = rapid(); app.setSelectedCluster(r[0]?.cluster ?? 0); app.setCompareCluster(r[r.length - 1]?.cluster ?? 1) } },
    { title: 'Independent validation', body: 'Recorded floods (IMD-based inventory) were never used for clustering. Compare association strength with a simple elevation-band baseline.',
      run: () => { app.setSelectedCluster(null); app.setCompareCluster(null); app.setPage('validate') } },
    { title: 'Scientific report', body: 'Generate a PDF with data sources, methods, metrics, profiles, validation and limitations.',
      run: () => app.setPage('reports') },
  ]
  const s = steps[i]
  const [started, setStarted] = useState<number | null>(null)

  useEffect(() => { if (!s.cta) s.run?.(); setStarted(null) }, [i]) // eslint-disable-line react-hooks/exhaustive-deps

  const canNext = !s.ready || s.ready()
  return (
    <div className="panel absolute bottom-4 left-1/2 z-30 w-[420px] -translate-x-1/2 p-4" data-testid="demo-guide">
      <div className="flex items-center justify-between">
        <div className="label text-warn">Guided demo · {i + 1}/{steps.length}</div>
        <button onClick={onClose} aria-label="Close demo" className="text-ink-400 hover:text-white"><Icon name="close" className="h-4 w-4" /></button>
      </div>
      <div className="mt-1 text-[14px] font-semibold text-white">{s.title}</div>
      <p className="mt-1 text-[12px] leading-snug text-ink-300">{s.body}</p>
      <div className="mt-3 flex items-center gap-2">
        {i > 0 && <Button variant="ghost" onClick={() => setI(i - 1)}>Back</Button>}
        {s.cta && started === null && !canNext && <Button onClick={() => { setStarted(Date.now()); s.run?.() }} testId="demo-cta">{s.cta}</Button>}
        {s.cta && started !== null && !canNext && <span className="text-[11.5px] text-ink-400">Pipeline running — watch the stages…</span>}
        <div className="flex-1" />
        {i < steps.length - 1
          ? <Button onClick={() => setI(i + 1)} disabled={!canNext} testId="demo-next">Next</Button>
          : <Button onClick={onClose}>Finish</Button>}
      </div>
    </div>
  )
}
