import { useEffect, useMemo, useState } from 'react'
import { api, pollJob, type Experiment, type Job } from '../api'
import { Button, Chip, Segmented, Stat, fmt } from '../components/ui'
import StageList from '../components/StageList'
import { ClusterCompare, Dendrogram, DistributionStrips, ModelTable, PcaScatter } from '../components/Charts'
import { clusterColor, useApp } from '../store'

export default function Discover() {
  const app = useApp()
  const { regions, periods, featureSets, algorithms, regionId, setRegionId, periodId, setPeriodId, featureSet, setFeatureSet,
    algorithm, setAlgorithm, result, loadRun, selectedCluster, setSelectedCluster, compareCluster, setCompareCluster, refreshRegions } = app
  const [job, setJob] = useState<Job | null>(null)
  const [cached, setCached] = useState<Experiment[]>([])
  const [tab, setTab] = useState<'profile' | 'pca' | 'models'>('profile')
  const running = job?.status === 'running' || job?.status === 'queued'
  const hasRun = !!result && result.region.id === regionId
  const region = regions.find(r => r.id === regionId)

  useEffect(() => {
    api.experiments(regionId).then(r => setCached(r.items)).catch(() => setCached([]))
  }, [regionId, result?.run_id])

  const matching = useMemo(() => cached.filter(e => e.period === periodId && e.feature_set === featureSet &&
    (algorithm === 'auto' || e.algorithm === algorithm)), [cached, periodId, featureSet, algorithm])

  const discover = async () => {
    setSelectedCluster(null); setCompareCluster(null)
    const { job_id } = await api.run({ region: regionId, period: periodId, feature_set: featureSet, algorithm })
    const j = await pollJob(job_id, setJob)
    if (j.status === 'done' && j.result_id) await loadRun(j.result_id)
    refreshRegions().catch(() => undefined)
  }

  const clickCluster = (c: number) => {
    if (selectedCluster === c) { setSelectedCluster(compareCluster); setCompareCluster(null); return }
    if (compareCluster === c) { setCompareCluster(null); return }
    if (selectedCluster === null) setSelectedCluster(c)
    else setCompareCluster(c)
  }

  const sel = result?.selected.metrics
  return (
    <section className="panel scroll-thin absolute left-4 top-4 z-10 max-h-[calc(100%-2rem)] w-[352px] overflow-y-auto p-4" data-testid="discover-panel">
      <h2 className="text-[15px] font-semibold text-white">Discover behaviour groups</h2>
      <div className="mt-3 space-y-3">
        <Step n={1} label="Region">
          <Segmented value={regionId} onChange={setRegionId} options={regions.map(r => ({ value: r.id, label: r.name.replace(' Himalaya', '') }))} />
        </Step>
        <Step n={2} label="Rainfall period (CHIRPS)">
          <Segmented testId="period-select" value={periodId} onChange={setPeriodId} size="sm" options={periods.map(p => ({
            value: p.id, label: `${p.id.replace('-', '–')}${region?.periods_cached && !region.periods_cached.includes(p.id) ? ' ↓' : ''}`,
            hint: region?.periods_cached?.includes(p.id) ? 'Rainfall data cached locally' : 'Rainfall data will be downloaded from CHIRPS first (slow)' }))} />
          {region?.periods_cached && !region.periods_cached.includes(periodId) && (
            <p className="mt-1 text-[10.5px] text-warn">CHIRPS years for this period are not cached yet — the first run downloads them (several minutes per year).</p>
          )}
        </Step>
        <Step n={3} label="Features">
          <Segmented testId="featureset-select" value={featureSet} onChange={setFeatureSet} size="sm"
            options={featureSets.map(f => ({ value: f.id, label: f.label.replace('Full behavioural', 'Full'), hint: f.description }))} />
        </Step>
        <Step n={4} label="Algorithm">
          <div className="grid grid-cols-3 gap-1" role="radiogroup" data-testid="algorithm-select">
            {algorithms.map(a => (
              <button key={a.id} role="radio" aria-checked={algorithm === a.id} title={a.purpose} onClick={() => setAlgorithm(a.id)}
                className={`rounded-md px-1.5 py-1.5 text-[11px] font-medium ${algorithm === a.id ? 'bg-ink-700 text-white ring-1 ring-accent/60' : 'bg-ink-950/70 text-ink-400 hover:text-ink-200'}`}>
                {a.name.replace('Hierarchical (Ward)', 'Ward').replace('Gaussian Mixture', 'GMM')}
              </button>
            ))}
          </div>
          <p className="mt-1 text-[10.5px] text-ink-500">{algorithms.find(a => a.id === algorithm)?.purpose}</p>
        </Step>
        <Button className="w-full py-2.5 text-[13px]" onClick={discover} disabled={running || !region?.prepared} testId="discover-button">
          {running ? 'Discovering…' : 'DISCOVER GROUPS'}
        </Button>
        {!running && matching.length > 0 && (!hasRun || result.run_id !== matching[0].run_id) && (
          <button onClick={() => loadRun(matching[0].run_id)} data-testid="replay-cached"
            className="w-full rounded-lg border border-dashed border-ink-600 px-2 py-1.5 text-[11px] text-ink-300 hover:border-accent hover:text-accent">
            Replay cached experiment · {new Date(matching[0].created_at).toLocaleString()} · {matching[0].algorithm_name}
          </button>
        )}
      </div>

      {job && running && <div className="mt-4"><StageList job={job} /></div>}
      {job?.status === 'failed' && <div className="mt-4"><StageList job={job} /></div>}

      {hasRun && sel && !running && (
        <div className="mt-4 border-t border-white/5 pt-4" data-testid="results">
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Algorithm" value={<span className="text-[13px]">{result.algorithm_name.replace('Hierarchical (Ward)', 'Ward')}</span>}
              sub={Object.entries(result.selected.params).filter(([k]) => k !== 'covariance' && k !== 'eps_quantile').map(([k, v]) => `${k}=${v}`).join(' ')} />
            <Stat label="Groups" value={sel.n_clusters} accent />
            <Stat label="Silhouette" value={fmt(sel.silhouette, 2)} sub={`stability ${fmt(sel.stability, 2)}`} />
            <Stat label="Catchments" value={result.assignments.length} />
            <Stat label="Noise" value={sel.n_noise} sub={`${fmt(sel.noise_fraction * 100, 0)}%`} />
            <Stat label="Elev. baseline" value={fmt(result.baseline.metrics.silhouette, 2)} sub="silhouette" />
          </div>
          {result.recommended_algorithm !== result.algorithm && (
            <p className="mt-2 text-[10.5px] text-ink-400">Most defensible by internal criteria: <span className="text-ink-200">{result.comparison.find(c => c.algorithm === result.recommended_algorithm)?.name}</span></p>
          )}
          {result.stage_log && <p className="mt-1 text-[10.5px] text-ink-500">Computed {new Date(result.created_at).toLocaleString()} in {result.duration_s}s · {result.dataset_version}</p>}

          <div className="label mb-1 mt-4">Groups <span className="normal-case tracking-normal text-ink-500">— click to highlight, click another to compare</span></div>
          <div className="space-y-0.5" data-testid="cluster-list">
            {result.profiles.map(p => (
              <Chip key={p.cluster} color={clusterColor(p.cluster)} active={selectedCluster === p.cluster || compareCluster === p.cluster}
                onClick={() => clickCluster(p.cluster)} testId={`cluster-${p.cluster}`}>
                <span className="flex justify-between gap-2"><span className="truncate">{p.name}</span><span className="num text-ink-400">{p.n_catchments}</span></span>
              </Chip>
            ))}
          </div>

          <div className="mt-4"><Segmented size="sm" value={tab} onChange={setTab} options={[
            { value: 'profile', label: 'Compare' }, { value: 'pca', label: 'PCA view' }, { value: 'models', label: 'Models' }]} /></div>
          <div className="mt-3">
            {tab === 'profile' && <><ClusterCompare result={result} a={selectedCluster} b={compareCluster} /><DistributionStrips result={result} focus={[selectedCluster, compareCluster]} /></>}
            {tab === 'pca' && <PcaScatter result={result} highlight={[selectedCluster, compareCluster]} />}
            {tab === 'models' && <><ModelTable result={result} /><Dendrogram result={result} /></>}
          </div>
        </div>
      )}
    </section>
  )
}

function Step({ n, label, children }: { n: number; label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-2">
        <span className="num flex h-4 w-4 items-center justify-center rounded-full bg-ink-700 text-[9.5px] text-ink-200">{n}</span>
        <span className="label">{label}</span>
      </div>
      {children}
    </div>
  )
}
