// Typed client for the HillScope FastAPI backend.

export type Region = {
  id: string; name: string; country: string; bbox: [number, number, number, number]
  center: [number, number]; prepared: boolean; periods_ready: string[]; periods_cached?: string[]; min_mean_elev_m: number
}
export type Period = { id: string; label: string; start: number; end: number }
export type FeatureSet = { id: string; label: string; description: string }
export type Algorithm = { id: string; name: string; family: string; purpose: string }

export type Metrics = {
  n_clusters: number; noise_fraction: number; n_noise: number; cluster_sizes: number[]
  min_cluster_fraction: number; silhouette: number | null; davies_bouldin: number | null
  calinski_harabasz: number | null; separation_ratio: number | null; stability: number | null
  selection_score: number; bic?: number; aic?: number; inertia?: number
}
export type Candidate = { algorithm: string; name: string; params: Record<string, unknown>; metrics: Metrics; extra: Record<string, unknown> }
export type FeatureMeta = { key: string; label: string; group: string; unit: string; nature: string; description: string }
export type Distinguishing = { feature: string; label: string; z: number; direction: string; cluster_median: number; region_median: number; unit: string; nature: string }
export type Profile = {
  cluster: number; name: string; traits: string[]; n_catchments: number; share: number; summary: string
  distinguishing: Distinguishing[]; stats: Record<string, { median: number | null; p25: number | null; p75: number | null; mean: number | null }>
  z_profile: Record<string, number>
}
export type Assignment = { catchment_id: string; cluster: number; baseline_band: number; probability: number | null; pca: number[]; district: string }
export type GroupAssoc = {
  group: number; name: string; n_catchments: number; n_events: number; catchments_with_events: number
  association_rate: number; events_per_catchment: number; events_per_catchment_year: number; lift: number | null; districts_spanned: number | null
}
export type Association = { groups: GroupAssoc[]; kruskal_H: number | null; kruskal_p: number | null; epsilon_squared: number | null; rate_ratio_max_min: number | null; overall_events_per_catchment_year: number }
export type ValidationBlock = {
  n_events: number; n_events_matched: number; catchments_with_events: number; spatial_coverage: number
  clusters: Association; baseline: Association; baseline_same_k: Association; counts: number[]
}
export type StageInfo = { label: string; status: string; messages: { t: string; m: string }[]; started: string | null; finished: string | null }

export type RunResult = {
  run_id: string; created_at: string; region: Region; period: Period; feature_set: FeatureSet
  algorithm: string; algorithm_name: string; requested_algorithm: string; recommended_algorithm: string
  selected: Candidate; comparison: Candidate[]; sweep: { params: Record<string, unknown>; metrics: Metrics }[]
  selection_rule: string
  preprocessing: Record<string, unknown> & { features_used: string[]; dropped_redundant: { feature: string; redundant_with: string; rho: number }[]; log_transformed: string[] }
  features: FeatureMeta[]; assignments: Assignment[]; profiles: Profile[]
  baseline: { bands: { band: number; name: string; min_m: number; max_m: number; n_catchments: number }[]; metrics: Metrics; same_k_metrics: Metrics }
  pca: { explained_variance: number[]; loadings: number[][]; note: string }
  dendrogram: { icoord: number[][]; dcoord: number[][]; leaves: string[]; max_height: number } | null
  validation: { windows: Record<string, { years: [number, number]; all: ValidationBlock; flash: ValidationBlock }>; notes: string[] }
  datasets: Record<string, unknown>; issues: { dataset: string; message: string }[]
  filters: Record<string, number>; dataset_version: string; duration_s: number; stage_log?: Record<string, StageInfo>
}
export type Job = {
  id: string; kind: string; status: 'queued' | 'running' | 'done' | 'failed'; stage: string | null; message: string | null
  stages: Record<string, StageInfo>; result_id: string | null; error: string | null
}
export type Experiment = {
  run_id: string; region: string; period: string; feature_set: string; algorithm: string; algorithm_name: string
  params: Record<string, unknown>; n_clusters: number; n_catchments: number; silhouette: number | null
  dataset_version: string; created_at: string; duration_s: number
}
export type DatasetStatus = {
  id: string; name: string; provider: string; url: string; license: string; nature: string; role: string
  status: string; issue: string | null; files: number; bytes: number; versions: string[]; last_retrieved: string | null
}
export type CatchmentDetail = {
  catchment_id: string; features: (FeatureMeta & { value: number; percentile: number })[]
  centroid: [number, number]
  assignment?: Assignment & { profile_name: string | null; profile_summary: string | null }
  recorded_events_concurrent?: number | null
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!r.ok) {
    let msg = r.statusText
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* not json */ }
    throw new ApiError(r.status, msg)
  }
  return r.json() as Promise<T>
}

export const api = {
  regions: () => req<{ regions: Region[]; periods: Period[]; feature_sets: FeatureSet[] }>('/api/regions'),
  algorithms: () => req<{ algorithms: Algorithm[] }>('/api/clustering/algorithms'),
  catchments: (region: string) => req<GeoJSON.FeatureCollection & { bbox: number[] }>(`/api/catchments?region=${region}`),
  catchment: (id: string, region: string, period: string, runId?: string) =>
    req<CatchmentDetail>(`/api/catchments/${id}?region=${region}&period=${period}${runId ? `&run_id=${runId}` : ''}`),
  events: (region: string) => req<{ footprints: GeoJSON.FeatureCollection; points: GeoJSON.FeatureCollection }>(`/api/events?region=${region}`),
  districtEvents: (region: string, start: number, end: number, flash: boolean) =>
    req<GeoJSON.FeatureCollection>(`/api/events/districts?region=${region}&start=${start}&end=${end}&flash_only=${flash}`),
  datasets: (region?: string) => req<{ datasets: DatasetStatus[] }>(`/api/datasets/status${region ? `?region=${region}` : ''}`),
  acquire: (region: string, period: string) => req<{ job_id: string }>('/api/data/acquire', { method: 'POST', body: JSON.stringify({ region, period }) }),
  run: (body: { region: string; period: string; feature_set: string; algorithm: string }) =>
    req<{ job_id: string }>('/api/clustering/run', { method: 'POST', body: JSON.stringify(body) }),
  job: (id: string) => req<Job>(`/api/jobs/${id}`),
  result: (runId: string) => req<RunResult>(`/api/clustering/results/${runId}`),
  experiments: (region?: string) => req<{ total: number; items: Experiment[] }>(`/api/experiments?page_size=50${region ? `&region=${region}` : ''}`),
  generateReport: (runId: string) => req<{ report_id: string; url: string; pages: number }>('/api/reports/generate', { method: 'POST', body: JSON.stringify({ run_id: runId }) }),
  reports: (runId?: string) => req<{ items: { report_id: string; run_id: string; pages: number; url: string; created_at: string }[] }>(`/api/reports${runId ? `?run_id=${runId}` : ''}`),
}

export async function pollJob(id: string, onUpdate: (j: Job) => void, intervalMs = 900): Promise<Job> {
  let failures = 0
  for (;;) {
    try {
      const j = await api.job(id)
      failures = 0
      onUpdate(j)
      if (j.status === 'done' || j.status === 'failed') return j
    } catch (e) {
      // Tolerate brief API outages (e.g. restart); give up after ~1 minute.
      if (e instanceof ApiError && e.status === 404) throw e
      if (++failures > 60) throw e
    }
    await new Promise(r => setTimeout(r, intervalMs))
  }
}
