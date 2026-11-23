import { useEffect, useState } from 'react'
import { api, pollJob, type DatasetStatus, type Job } from '../api'
import { Button, Segmented } from '../components/ui'
import StageList from '../components/StageList'
import { useApp } from '../store'

export default function Explore() {
  const { regions, regionId, setRegionId, result, setPage, refreshRegions } = useApp()
  const region = regions.find(r => r.id === regionId)
  const [ds, setDs] = useState<DatasetStatus[]>([])
  const [job, setJob] = useState<Job | null>(null)

  useEffect(() => { api.datasets(regionId).then(r => setDs(r.datasets)).catch(() => setDs([])) }, [regionId, job?.status])

  const prepare = async () => {
    const { job_id } = await api.acquire(regionId, '2001-2020')
    const j = await pollJob(job_id, setJob)
    if (j.status === 'done') await refreshRegions()
  }

  const hasRun = result && result.region.id === regionId
  return (
    <section className="panel absolute left-4 top-4 z-10 w-[330px] p-4" data-testid="explore-panel">
      <h1 className="text-[15px] font-semibold tracking-tight text-white">Hill catchment behaviour</h1>
      <p className="mt-1 text-[12px] leading-snug text-ink-400">
        Catchments receiving similar rain can respond very differently. Explore real HydroBASINS catchments, then let unsupervised learning find the hidden groups.
      </p>
      <div className="mt-3">
        <div className="label mb-1.5">Study region</div>
        <Segmented testId="region-select" value={regionId} onChange={setRegionId}
          options={regions.map(r => ({ value: r.id, label: r.name.replace(' Himalaya', '') }))} />
      </div>
      {region && !region.prepared && (
        <div className="mt-3 rounded-lg bg-ink-950/60 p-3 text-[12px] text-ink-300 ring-1 ring-white/5">
          Real datasets for this region are not cached yet.
          <Button className="mt-2 w-full" onClick={prepare} disabled={job?.status === 'running' || job?.status === 'queued'} testId="prepare-region">Acquire &amp; prepare data</Button>
          {job && <div className="mt-2"><StageList job={job} /></div>}
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-1" data-testid="dataset-dots">
        {ds.map(d => (
          <span key={d.id} title={`${d.name} — ${d.status}${d.issue ? `: ${d.issue}` : ''}`}
            className={`rounded px-1.5 py-0.5 text-[9.5px] font-medium ${
              d.status === 'cached' ? 'bg-emerald-500/10 text-emerald-300' : d.status === 'unavailable' ? 'bg-red-500/10 text-red-300' : 'bg-ink-800 text-ink-400'}`}>
            {d.id.replace('_', ' ')}
          </span>
        ))}
      </div>
      <div className="mt-3 border-t border-white/5 pt-3">
        {hasRun ? (
          <div className="text-[12px] text-ink-300">
            Showing <span className="text-white">{result.profiles.filter(p => p.cluster >= 0).length} groups</span> from {result.algorithm_name} · {result.period.label}
            <button className="ml-1 text-accent hover:underline" onClick={() => setPage('discover')}>details →</button>
          </div>
        ) : (
          <Button className="w-full" onClick={() => setPage('discover')} testId="go-discover" disabled={!region?.prepared}>Discover behaviour groups →</Button>
        )}
      </div>
    </section>
  )
}
