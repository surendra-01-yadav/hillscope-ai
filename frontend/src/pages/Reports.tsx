import { useEffect, useState } from 'react'
import { api, type DatasetStatus, type Experiment } from '../api'
import { Button, Icon, NatureBadge, fmt } from '../components/ui'
import { useApp } from '../store'

export default function Reports() {
  const { result, regionId, loadRun } = useApp()
  const [reports, setReports] = useState<{ report_id: string; run_id: string; pages: number; url: string; created_at: string }[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [ds, setDs] = useState<DatasetStatus[]>([])
  const [exps, setExps] = useState<Experiment[]>([])
  const hasRun = !!result && result.region.id === regionId

  useEffect(() => {
    api.datasets(regionId).then(r => setDs(r.datasets)).catch(() => setDs([]))
    api.experiments(regionId).then(r => setExps(r.items)).catch(() => setExps([]))
  }, [regionId])
  useEffect(() => { api.reports(hasRun ? result.run_id : undefined).then(r => setReports(r.items)).catch(() => setReports([])) }, [hasRun, result?.run_id])

  const generate = async () => {
    if (!result) return
    setBusy(true); setErr(null)
    try {
      const r = await api.generateReport(result.run_id)
      setReports(rs => [{ report_id: r.report_id, run_id: result.run_id, pages: r.pages, url: r.url, created_at: new Date().toISOString() }, ...rs])
      window.open(r.url, '_blank')
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <div className="absolute inset-0 z-10 overflow-y-auto bg-ink-950/80 backdrop-blur-sm" data-testid="reports-page">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <h2 className="text-lg font-semibold text-white">Reports</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-[1.1fr_1fr]">
          <section className="panel p-4">
            <div className="label">Scientific report</div>
            {hasRun ? (
              <>
                <div className="mt-2 text-sm text-white">{result.region.name} · {result.algorithm_name} · {result.period.label}</div>
                <div className="num mt-0.5 text-[11px] text-ink-400">run {result.run_id} · {result.dataset_version} · {result.profiles.filter(p => p.cluster >= 0).length} groups · silhouette {fmt(result.selected.metrics.silhouette, 3)}</div>
                <p className="mt-3 text-[12px] leading-relaxed text-ink-300">Includes study region, data sources and provenance, feature methodology, algorithm comparison, cluster profiles, historical association, elevation-baseline comparison, limitations and conclusions.</p>
                <Button className="mt-3" onClick={generate} disabled={busy} testId="generate-report">{busy ? 'Generating PDF…' : 'Generate PDF report'}</Button>
                {err && <div className="mt-2 text-xs text-red-300">{err}</div>}
              </>
            ) : <p className="mt-2 text-[12px] text-ink-400">Run or replay a discovery to generate a report.</p>}
            {reports.length > 0 && (
              <ul className="mt-4 space-y-1" data-testid="report-list">
                {reports.map(r => (
                  <li key={r.report_id}>
                    <a href={r.url} target="_blank" rel="noreferrer" className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[12px] text-ink-200 hover:bg-ink-800">
                      <Icon name="download" className="h-4 w-4 text-accent" />
                      <span className="num">report_{r.run_id}.pdf</span>
                      <span className="ml-auto text-[10.5px] text-ink-500">{r.pages} pp · {new Date(r.created_at).toLocaleString()}</span>
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="panel p-4">
            <div className="label">Experiment history</div>
            <ul className="scroll-thin mt-2 max-h-64 space-y-0.5 overflow-y-auto" data-testid="experiment-list">
              {exps.map(e => (
                <li key={e.run_id}>
                  <button onClick={() => loadRun(e.run_id)} className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[11.5px] hover:bg-ink-800 ${result?.run_id === e.run_id ? 'bg-ink-800' : ''}`}>
                    <span className="w-28 truncate text-ink-100">{e.algorithm_name}</span>
                    <span className="num text-ink-400">{e.period}</span>
                    <span className="num text-ink-400">k={e.n_clusters}</span>
                    <span className="num ml-auto text-ink-500">{fmt(e.silhouette, 2)}</span>
                  </button>
                </li>
              ))}
              {!exps.length && <li className="text-[12px] text-ink-500">No experiments yet.</li>}
            </ul>
          </section>
        </div>
        <section className="panel mt-4 p-4">
          <div className="label">Data sources &amp; integrity</div>
          <table className="mt-2 w-full text-[11.5px]" data-testid="dataset-table">
            <thead><tr className="text-left text-ink-500"><th className="pb-1 font-medium">Dataset</th><th className="font-medium">Nature</th><th className="font-medium">Role</th><th className="font-medium">Status</th><th className="font-medium">Retrieved</th></tr></thead>
            <tbody>
              {ds.map(d => (
                <tr key={d.id} className="border-t border-white/5 align-top">
                  <td className="py-1.5 pr-2"><a href={d.url} target="_blank" rel="noreferrer" className="text-ink-100 hover:text-accent">{d.name}</a><div className="text-[10.5px] text-ink-500">{d.provider} · {d.license}</div></td>
                  <td className="pr-2"><NatureBadge nature={d.nature} /></td>
                  <td className="pr-2 text-ink-300">{d.role}</td>
                  <td className={`pr-2 ${d.status === 'cached' ? 'text-emerald-300' : d.status === 'unavailable' ? 'text-red-300' : 'text-ink-400'}`} title={d.issue ?? ''}>
                    {d.status}{d.files ? <span className="num text-ink-500"> · {d.files} files · {(d.bytes / 1e6).toFixed(1)} MB</span> : ''}
                  </td>
                  <td className="num text-[10.5px] text-ink-500">{d.last_retrieved ? new Date(d.last_retrieved).toLocaleDateString() : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  )
}
