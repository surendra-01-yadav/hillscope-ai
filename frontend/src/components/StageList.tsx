import type { Job } from '../api'
import { Icon } from './ui'

/** Renders the real stage log reported by the backend job (no simulated progress). */
export default function StageList({ job }: { job: Job }) {
  const entries = Object.entries(job.stages ?? {})
  return (
    <ol className="space-y-1.5" data-testid="stage-list">
      {job.status === 'queued' && <li className="text-[11px] text-warn">Queued — waiting for another running job to finish…</li>}
      {entries.map(([k, s]) => {
        const last = s.messages[s.messages.length - 1]?.m
        return (
          <li key={k} className="flex gap-2">
            <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
              {s.status === 'done' && <Icon name="check" className="h-4 w-4 text-accent" />}
              {s.status === 'running' && <span className="pulse h-2 w-2 rounded-full bg-warn" />}
              {s.status === 'failed' && <span className="h-2 w-2 rounded-full bg-danger" />}
              {(s.status === 'pending' || s.status === 'skipped') && <span className="h-1.5 w-1.5 rounded-full bg-ink-600" />}
            </span>
            <div className="min-w-0">
              <div className={`text-[12px] ${s.status === 'pending' ? 'text-ink-500' : 'text-ink-100'}`}>{s.label}</div>
              {last && s.status !== 'pending' && <div className="num truncate text-[10.5px] text-ink-400" title={last}>{last}</div>}
            </div>
          </li>
        )
      })}
      {job.status === 'failed' && <li className="rounded bg-red-500/10 p-2 text-[11px] text-red-200" data-testid="job-error">{job.error}</li>}
    </ol>
  )
}
