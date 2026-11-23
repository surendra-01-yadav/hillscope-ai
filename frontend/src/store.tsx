import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, type Algorithm, type FeatureSet, type Period, type Region, type RunResult } from './api'

export type Page = 'explore' | 'discover' | 'validate' | 'reports'
export type Basemap = 'dark' | 'satellite'

export const CLUSTER_COLORS = ['#3b8eea', '#ef6a3a', '#1fbf8f', '#f2b134', '#9b6cd8', '#e2559d', '#58c4dd', '#a3b33c']
export const NOISE_COLOR = '#8a929c'
export const clusterColor = (c: number) => (c < 0 ? NOISE_COLOR : CLUSTER_COLORS[c % CLUSTER_COLORS.length])

type State = {
  page: Page; setPage: (p: Page) => void
  regions: Region[]; periods: Period[]; featureSets: FeatureSet[]; algorithms: Algorithm[]
  regionId: string; setRegionId: (r: string) => void
  periodId: string; setPeriodId: (p: string) => void
  featureSet: string; setFeatureSet: (f: string) => void
  algorithm: string; setAlgorithm: (a: string) => void
  result: RunResult | null; setResult: (r: RunResult | null) => void
  loadRun: (runId: string) => Promise<void>
  selectedCatchment: string | null; setSelectedCatchment: (id: string | null) => void
  selectedCluster: number | null; setSelectedCluster: (c: number | null) => void
  compareCluster: number | null; setCompareCluster: (c: number | null) => void
  basemap: Basemap; setBasemap: (b: Basemap) => void
  hillshade: boolean; setHillshade: (v: boolean) => void
  showGroups: boolean; setShowGroups: (v: boolean) => void
  showEvents: boolean; setShowEvents: (v: boolean) => void
  bootError: string | null
  refreshRegions: () => Promise<void>
}

const Ctx = createContext<State | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<Page>(() => (['explore', 'discover', 'validate', 'reports'].includes(location.hash.slice(1)) ? location.hash.slice(1) as Page : 'explore'))
  const [regions, setRegions] = useState<Region[]>([])
  const [periods, setPeriods] = useState<Period[]>([])
  const [featureSets, setFeatureSets] = useState<FeatureSet[]>([])
  const [algorithms, setAlgorithms] = useState<Algorithm[]>([])
  const [regionId, setRegionIdRaw] = useState('uttarakhand')
  const [periodId, setPeriodId] = useState('2001-2020')
  const [featureSet, setFeatureSet] = useState('behavioural')
  const [algorithm, setAlgorithm] = useState('kmeans')
  const [result, setResult] = useState<RunResult | null>(null)
  const [selectedCatchment, setSelectedCatchment] = useState<string | null>(null)
  const [selectedCluster, setSelectedCluster] = useState<number | null>(null)
  const [compareCluster, setCompareCluster] = useState<number | null>(null)
  const [basemap, setBasemap] = useState<Basemap>('dark')
  const [hillshade, setHillshade] = useState(true)
  const [showGroups, setShowGroups] = useState(true)
  const [showEvents, setShowEvents] = useState(false)
  const [bootError, setBootError] = useState<string | null>(null)

  const refreshRegions = useCallback(async () => {
    const r = await api.regions()
    setRegions(r.regions); setPeriods(r.periods); setFeatureSets(r.feature_sets)
  }, [])

  useEffect(() => {
    // Retry until the API is reachable (e.g. while uvicorn is still starting).
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const boot = () => Promise.all([refreshRegions(), api.algorithms().then(a => setAlgorithms(a.algorithms))])
      .then(() => { if (!cancelled) setBootError(null) })
      .catch(e => { if (!cancelled) { setBootError(`Backend unreachable: ${e.message}`); timer = setTimeout(boot, 3000) } })
    boot()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [refreshRegions])

  useEffect(() => { if (location.hash.slice(1) !== page) history.replaceState(null, '', `#${page}`) }, [page])
  useEffect(() => {
    const onHash = () => {
      const h = location.hash.slice(1) as Page
      if (['explore', 'discover', 'validate', 'reports'].includes(h)) setPage(h)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const setRegionId = useCallback((r: string) => {
    setRegionIdRaw(r); setResult(null); setSelectedCatchment(null); setSelectedCluster(null); setCompareCluster(null)
  }, [])

  const loadRun = useCallback(async (runId: string) => {
    const r = await api.result(runId)
    setRegionIdRaw(r.region.id); setPeriodId(r.period.id); setFeatureSet(r.feature_set.id)
    setAlgorithm(r.requested_algorithm || r.algorithm)
    setResult(r); setSelectedCluster(null); setCompareCluster(null)
  }, [])

  const value = useMemo<State>(() => ({
    page, setPage, regions, periods, featureSets, algorithms, regionId, setRegionId, periodId, setPeriodId,
    featureSet, setFeatureSet, algorithm, setAlgorithm, result, setResult, loadRun, selectedCatchment,
    setSelectedCatchment, selectedCluster, setSelectedCluster, compareCluster, setCompareCluster, basemap,
    setBasemap, hillshade, setHillshade, showGroups, setShowGroups, showEvents, setShowEvents, bootError, refreshRegions,
  }), [page, regions, periods, featureSets, algorithms, regionId, setRegionId, periodId, featureSet, algorithm, result,
    loadRun, selectedCatchment, selectedCluster, compareCluster, basemap, hillshade, showGroups, showEvents, bootError, refreshRegions])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp outside AppProvider')
  return v
}

export function profileName(result: RunResult | null, c: number) {
  return result?.profiles.find(p => p.cluster === c)?.name ?? (c < 0 ? 'Noise' : `Group ${c}`)
}
