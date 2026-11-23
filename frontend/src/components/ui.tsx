import type { ReactNode } from 'react'

export function Segmented<T extends string>({ value, options, onChange, size = 'md', testId }: {
  value: T; options: { value: T; label: string; hint?: string }[]; onChange: (v: T) => void; size?: 'sm' | 'md'; testId?: string
}) {
  return (
    <div className="flex rounded-lg bg-ink-950/70 p-0.5 ring-1 ring-white/5" role="radiogroup" data-testid={testId}>
      {options.map(o => (
        <button key={o.value} role="radio" aria-checked={value === o.value} title={o.hint}
          onClick={() => onChange(o.value)}
          className={`flex-1 rounded-md px-2 ${size === 'sm' ? 'py-1 text-[11px]' : 'py-1.5 text-xs'} font-medium transition-colors ${
            value === o.value ? 'bg-ink-700 text-white shadow-sm' : 'text-ink-400 hover:text-ink-200'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Stat({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: ReactNode; accent?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="label truncate">{label}</div>
      <div className={`num mt-0.5 text-lg font-medium leading-tight ${accent ? 'text-accent' : 'text-ink-100'}`}>{value}</div>
      {sub && <div className="mt-0.5 truncate text-[10.5px] text-ink-400">{sub}</div>}
    </div>
  )
}

export function Chip({ color, children, active, onClick, testId }: { color?: string; children: ReactNode; active?: boolean; onClick?: () => void; testId?: string }) {
  return (
    <button onClick={onClick} data-testid={testId}
      className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition ${
        active ? 'bg-ink-700/80 ring-1 ring-white/15' : 'hover:bg-ink-800'}`}>
      {color && <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: color }} />}
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </button>
  )
}

export function NatureBadge({ nature }: { nature: string }) {
  const n = nature.toLowerCase()
  const cls = n.includes('estimated') ? 'bg-amber-500/15 text-amber-300'
    : n.includes('model') ? 'bg-violet-500/15 text-violet-300'
    : n.includes('remote') ? 'bg-sky-500/15 text-sky-300'
    : n.includes('observed') ? 'bg-emerald-500/15 text-emerald-300' : 'bg-ink-700 text-ink-300'
  const short = n.includes('estimated') ? 'estimated' : n.includes('model') ? 'model' : n.includes('observed') ? 'observed' : n.includes('remote') ? 'remote sensed' : nature
  return <span className={`rounded px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide ${cls}`} title={nature}>{short}</span>
}

export function Button({ children, onClick, disabled, variant = 'primary', testId, className = '' }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; variant?: 'primary' | 'ghost'; testId?: string; className?: string
}) {
  return (
    <button onClick={onClick} disabled={disabled} data-testid={testId}
      className={`rounded-lg px-3 py-2 text-xs font-semibold tracking-wide transition disabled:cursor-not-allowed disabled:opacity-40 ${
        variant === 'primary' ? 'bg-accent text-ink-950 hover:brightness-110' : 'bg-ink-800 text-ink-200 ring-1 ring-white/10 hover:bg-ink-700'} ${className}`}>
      {children}
    </button>
  )
}

export function Icon({ name, className = 'h-5 w-5' }: { name: 'explore' | 'discover' | 'validate' | 'reports' | 'layers' | 'close' | 'play' | 'check' | 'info' | 'download'; className?: string }) {
  const p = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  const paths: Record<string, ReactNode> = {
    explore: <><path {...p} d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z" /><path {...p} d="M9 4v14M15 6v14" /></>,
    discover: <><circle {...p} cx="7" cy="8" r="2.5" /><circle {...p} cx="16.5" cy="7" r="2" /><circle {...p} cx="11" cy="16.5" r="3" /><path {...p} d="M9.2 9.5l1.2 4M14.8 8.2l-2.4 6" /></>,
    validate: <><path {...p} d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z" /><path {...p} d="M8.5 12l2.3 2.3 4.7-4.8" /></>,
    reports: <><path {...p} d="M7 3h7l5 5v13H7z" /><path {...p} d="M14 3v5h5M10 13h6M10 17h6" /></>,
    layers: <><path {...p} d="M12 3l9 5-9 5-9-5z" /><path {...p} d="M3 13l9 5 9-5" /></>,
    close: <path {...p} d="M6 6l12 12M18 6L6 18" />,
    play: <path {...p} d="M8 5l11 7-11 7z" />,
    check: <path {...p} d="M5 12.5l4.5 4.5L19 7.5" />,
    info: <><circle {...p} cx="12" cy="12" r="9" /><path {...p} d="M12 11v6M12 7.5v.01" /></>,
    download: <><path {...p} d="M12 4v11M7 10.5l5 5 5-5M5 20h14" /></>,
  }
  return <svg viewBox="0 0 24 24" className={className} aria-hidden>{paths[name]}</svg>
}

export const fmt = (v: number | null | undefined, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? '–' : v.toFixed(d))
