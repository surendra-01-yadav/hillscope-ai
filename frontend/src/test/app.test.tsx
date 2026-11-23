// UI behaviour tests. The API is mocked with a small hand-written fixture (test input only);
// MapLibre needs WebGL so the map is replaced with a stub that exposes catchment selection.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { AppProvider, useApp } from '../store'

vi.mock('../components/MapView', () => ({
  default: ({ colorMode }: { colorMode: string }) => {
    const { setSelectedCatchment, selectedCluster } = useApp()
    return (
      <div data-testid="map" data-mode={colorMode} data-selected-cluster={selectedCluster ?? ''}>
        <button onClick={() => setSelectedCatchment('4120001')}>pick-catchment</button>
      </div>
    )
  },
  BAND_COLORS: ['#1', '#2', '#3'],
  ELEV_STOPS: [[500, '#000'], [5500, '#fff']],
}))

const metrics = (k: number, sil: number) => ({ n_clusters: k, noise_fraction: 0, n_noise: 0, cluster_sizes: [2, 1], min_cluster_fraction: 0.3,
  silhouette: sil, davies_bouldin: 1.1, calinski_harabasz: 50, separation_ratio: 1.2, stability: 0.9, selection_score: 0.4 })
const assoc = (n: number) => ({ groups: Array.from({ length: n }, (_, g) => ({ group: g, name: `G${g}`, n_catchments: 1, n_events: g, catchments_with_events: 1,
  association_rate: 1, events_per_catchment: g, events_per_catchment_year: g / 10, lift: 1, districts_spanned: 1 })),
  kruskal_H: 3, kruskal_p: 0.01, epsilon_squared: 0.2, rate_ratio_max_min: 2, overall_events_per_catchment_year: 0.1 })
const block = { n_events: 5, n_events_matched: 5, catchments_with_events: 3, spatial_coverage: 1, clusters: assoc(2), baseline: assoc(3), baseline_same_k: assoc(2), counts: [1, 2, 0] }
const RESULT = {
  run_id: 'run123', created_at: '2026-11-23T00:00:00Z',
  region: { id: 'uttarakhand', name: 'Uttarakhand Himalaya', country: 'India', bbox: [77, 28, 81, 31], center: [79, 30], prepared: true, periods_ready: [], min_mean_elev_m: 500 },
  period: { id: '2001-2020', label: '2001 – 2020 (20 yr)', start: 2001, end: 2020 },
  feature_set: { id: 'behavioural', label: 'Full behavioural', description: '' },
  algorithm: 'kmeans', algorithm_name: 'K-Means', requested_algorithm: 'kmeans', recommended_algorithm: 'kmeans',
  selected: { algorithm: 'kmeans', name: 'K-Means', params: { k: 2 }, metrics: metrics(2, 0.31), extra: {} },
  comparison: [{ algorithm: 'kmeans', name: 'K-Means', params: { k: 2 }, metrics: metrics(2, 0.31), extra: {} }],
  sweep: [{ params: { k: 2 }, metrics: metrics(2, 0.31) }], selection_rule: 'rule',
  preprocessing: { features_used: ['slope_mean'], dropped_redundant: [], log_transformed: [] },
  features: [{ key: 'slope_mean', label: 'Mean slope', group: 'terrain', unit: '°', nature: 'remotely sensed', description: '' }],
  assignments: [
    { catchment_id: '4120001', cluster: 0, baseline_band: 0, probability: null, pca: [0, 1], district: 'Chamoli' },
    { catchment_id: '4120002', cluster: 0, baseline_band: 1, probability: null, pca: [1, 0], district: 'Chamoli' },
    { catchment_id: '4120003', cluster: 1, baseline_band: 2, probability: null, pca: [2, 2], district: 'Almora' }],
  profiles: [
    { cluster: 0, name: 'Rapid-response steep terrain', traits: [], n_catchments: 2, share: 0.67, summary: 'Compared with the region: higher mean slope.', distinguishing: [{ feature: 'slope_mean', label: 'Mean slope', z: 1.2, direction: 'higher', cluster_median: 30, region_median: 25, unit: '°', nature: 'remotely sensed' }], stats: {}, z_profile: { slope_mean: 1.2 } },
    { cluster: 1, name: 'Gentler, slower-response hills', traits: [], n_catchments: 1, share: 0.33, summary: 'Compared with the region: lower mean slope.', distinguishing: [{ feature: 'slope_mean', label: 'Mean slope', z: -1, direction: 'lower', cluster_median: 10, region_median: 25, unit: '°', nature: 'remotely sensed' }], stats: {}, z_profile: { slope_mean: -1 } }],
  baseline: { bands: [0, 1, 2].map(b => ({ band: b, name: ['Lower elevation', 'Middle elevation', 'Higher elevation'][b], min_m: b * 1000, max_m: b * 1000 + 1000, n_catchments: 1 })), metrics: metrics(3, 0.09), same_k_metrics: metrics(2, 0.1) },
  pca: { explained_variance: [0.4, 0.2], loadings: [], note: 'PCA' }, dendrogram: null,
  validation: { windows: { concurrent: { years: [2001, 2020], all: block, flash: block } }, notes: ['Events not used for clustering.'] },
  datasets: {}, issues: [], filters: {}, dataset_version: 'fv-abc', duration_s: 12,
}

let jobPolls = 0
function mockFetch(url: string, init?: RequestInit) {
  const ok = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
  if (url.startsWith('/api/regions')) return ok({ regions: [RESULT.region, { ...RESULT.region, id: 'himachal', name: 'Himachal Pradesh' }], periods: [RESULT.period], feature_sets: [RESULT.feature_set] })
  if (url.startsWith('/api/clustering/algorithms')) return ok({ algorithms: [{ id: 'kmeans', name: 'K-Means', family: 'centroid', purpose: 'p' }, { id: 'gmm', name: 'Gaussian Mixture', family: 'p', purpose: 'p' }] })
  if (url.startsWith('/api/datasets/status')) return ok({ datasets: [{ id: 'chirps', name: 'CHIRPS', provider: 'UCSB', url: '#', license: 'PD', nature: 'observed', role: 'rain', status: 'cached', issue: null, files: 20, bytes: 1e8, versions: [], last_retrieved: null },
    { id: 'discharge', name: 'Gauged discharge', provider: 'CWC', url: '#', license: 'R', nature: 'observed', role: 'NOT AVAILABLE', status: 'unavailable', issue: null, files: 0, bytes: 0, versions: [], last_retrieved: null }] })
  if (url.startsWith('/api/experiments')) return ok({ total: 0, items: [] })
  if (url.startsWith('/api/clustering/run') && init?.method === 'POST') return ok({ job_id: 'job1' })
  if (url.startsWith('/api/jobs/job1')) {
    jobPolls += 1
    const done = jobPolls > 1
    return ok({ id: 'job1', kind: 'clustering', status: done ? 'done' : 'running', stage: 'cluster', message: 'm', result_id: done ? 'run123' : null, error: null,
      stages: { acquire: { label: 'Acquiring datasets', status: 'done', messages: [{ t: '', m: 'cached' }], started: '', finished: '' },
        cluster: { label: 'Running clustering', status: done ? 'done' : 'running', messages: [{ t: '', m: 'K-Means: evaluated 3/7 configurations' }], started: '', finished: null } } })
  }
  if (url.startsWith('/api/clustering/results/run123')) return ok(RESULT)
  if (url.startsWith('/api/catchments/4120001')) return ok({ catchment_id: '4120001', centroid: [79, 30], features: [
    { key: 'area_km2', label: 'Catchment area', group: 'terrain', unit: 'km²', nature: 'remotely sensed', description: '', value: 140, percentile: 0.5 },
    { key: 'elev_mean', label: 'Mean elevation', group: 'terrain', unit: 'm', nature: 'remotely sensed', description: '', value: 2400, percentile: 0.6 },
    { key: 'slope_mean', label: 'Mean slope', group: 'terrain', unit: '°', nature: 'remotely sensed', description: '', value: 31, percentile: 0.9 }],
    assignment: { ...RESULT.assignments[0], profile_name: 'Rapid-response steep terrain', profile_summary: '' }, recorded_events_concurrent: 2 })
  if (url.startsWith('/api/events/districts')) return ok({ type: 'FeatureCollection', features: [] })
  if (url.startsWith('/api/reports/generate')) return ok({ report_id: 'rep1', url: '/api/reports/rep1', pages: 6 }, 201)
  if (url.startsWith('/api/reports')) return ok({ items: [] })
  return ok({ detail: 'not mocked' }, 404)
}

function renderApp() {
  return render(<AppProvider><App /></AppProvider>)
}

beforeEach(() => {
  jobPolls = 0
  location.hash = ''
  vi.stubGlobal('fetch', vi.fn((u: string, i?: RequestInit) => mockFetch(u, i)))
  vi.stubGlobal('open', vi.fn())
})

async function runDiscovery() {
  renderApp()
  fireEvent.click(await screen.findByTestId('nav-discover'))
  const btn = await screen.findByTestId('discover-button')
  await waitFor(() => expect(btn).not.toBeDisabled())
  await act(async () => { fireEvent.click(btn) })
  await screen.findByTestId('results', {}, { timeout: 5000 })
}

describe('HillScope UI', () => {
  it('has exactly four primary sections and navigates between them', async () => {
    renderApp()
    const nav = screen.getByRole('navigation', { name: 'Primary' })
    expect(within(nav).getAllByRole('button').map(b => b.textContent)).toEqual(['Explore', 'Discover', 'Validate', 'Reports', 'Demo'])
    expect(await screen.findByTestId('explore-panel')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('nav-reports'))
    expect(await screen.findByTestId('reports-page')).toBeInTheDocument()
    expect(location.hash).toBe('#reports')
  })

  it('renders the map and shows dataset status including unavailable discharge', async () => {
    renderApp()
    expect(screen.getByTestId('map')).toHaveAttribute('data-mode', 'elevation')
    const dots = await screen.findByTestId('dataset-dots')
    await waitFor(() => expect(within(dots).getByText('discharge')).toBeInTheDocument())
  })

  it('shows a compact panel when a catchment is selected', async () => {
    renderApp()
    fireEvent.click(screen.getByText('pick-catchment'))
    const panel = await screen.findByTestId('catchment-panel')
    await waitFor(() => expect(within(panel).getByText('2400 m')).toBeInTheDocument())
    expect(within(panel).getByText('4120001')).toBeInTheDocument()
  })

  it('runs the discovery workflow with real backend stage messages and shows results', async () => {
    await runDiscovery()
    const results = screen.getByTestId('results')
    expect(within(results).getByText('0.31')).toBeInTheDocument()
    expect(screen.getByTestId('map')).toHaveAttribute('data-mode', 'clusters')
    expect(fetch).toHaveBeenCalledWith('/api/clustering/run', expect.objectContaining({ method: 'POST' }))
  })

  it('highlights a cluster on click and compares two clusters', async () => {
    await runDiscovery()
    fireEvent.click(screen.getByTestId('cluster-0'))
    expect(screen.getByTestId('map')).toHaveAttribute('data-selected-cluster', '0')
    fireEvent.click(screen.getByTestId('cluster-1'))
    const cmp = screen.getByTestId('cluster-compare')
    expect(within(cmp).getByText(/Rapid-response steep terrain/)).toBeInTheDocument()
    expect(within(cmp).getByText(/Gentler, slower-response hills/)).toBeInTheDocument()
  })

  it('shows historical validation against the elevation baseline', async () => {
    await runDiscovery()
    fireEvent.click(screen.getByTestId('nav-validate'))
    const panel = await screen.findByTestId('validate-panel')
    expect(within(panel).getByText('Elevation baseline')).toBeInTheDocument()
    fireEvent.click(within(panel).getByText('Map: elevation bands'))
    expect(screen.getByTestId('map')).toHaveAttribute('data-mode', 'baseline')
    fireEvent.click(screen.getByTestId('methodology-toggle'))
    expect(screen.getByTestId('methodology')).toHaveTextContent('Events not used for clustering.')
  })

  it('generates and lists a PDF report', async () => {
    await runDiscovery()
    fireEvent.click(screen.getByTestId('nav-reports'))
    await act(async () => { fireEvent.click(await screen.findByTestId('generate-report')) })
    const list = await screen.findByTestId('report-list')
    expect(within(list).getByText('report_run123.pdf').closest('a')).toHaveAttribute('href', '/api/reports/rep1')
    expect(window.open).toHaveBeenCalledWith('/api/reports/rep1', '_blank')
  })

  it('opens the guided demo and advances through steps', async () => {
    renderApp()
    fireEvent.click(screen.getByTestId('demo-toggle'))
    const guide = await screen.findByTestId('demo-guide')
    expect(guide).toHaveTextContent('1/7')
    fireEvent.click(within(guide).getByTestId('demo-next'))
    await waitFor(() => expect(screen.getByTestId('discover-panel')).toBeInTheDocument())
    expect(screen.getByTestId('demo-guide')).toHaveTextContent('2/7')
  })
})
