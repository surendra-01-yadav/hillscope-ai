import { useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import type { GeoJSONSource, Map as MLMap, StyleSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { api } from '../api'
import { CLUSTER_COLORS, NOISE_COLOR, useApp } from '../store'

export type ColorMode = 'elevation' | 'clusters' | 'baseline'
export const BAND_COLORS = ['#7fb7a4', '#d9a55b', '#c46a6a']
export const ELEV_STOPS: [number, string][] = [[500, '#1f4d5a'], [1500, '#3f7f6e'], [2500, '#9a9a5b'], [3500, '#b58552'], [4500, '#c9b8a8'], [5500, '#f1f1f1']]

const STYLE: StyleSpecification = {
  version: 8,
  glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
  sources: {
    dark: { type: 'raster', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}'], tileSize: 256, maxzoom: 16, attribution: 'Basemap © Esri, HERE, Garmin, © OpenStreetMap contributors' },
    labels: { type: 'raster', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}'], tileSize: 256, maxzoom: 16 },
    satellite: { type: 'raster', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], tileSize: 256, maxzoom: 18, attribution: 'Imagery © Esri, Maxar, Earthstar Geographics' },
    dem: { type: 'raster-dem', tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'], tileSize: 256, encoding: 'terrarium', maxzoom: 13, attribution: 'Terrain: Mapzen/AWS Terrain Tiles' },
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#0b1015' } },
    { id: 'dark', type: 'raster', source: 'dark' },
    { id: 'satellite', type: 'raster', source: 'satellite', layout: { visibility: 'none' } },
    { id: 'hillshade', type: 'hillshade', source: 'dem', paint: { 'hillshade-exaggeration': 0.55, 'hillshade-shadow-color': '#05080b', 'hillshade-highlight-color': '#b8c4cf', 'hillshade-accent-color': '#1a242d' } },
  ],
}

type Props = {
  colorMode: ColorMode
  eventPoints?: GeoJSON.FeatureCollection | null
  onReady?: (map: MLMap) => void
}

export default function MapView({ colorMode, eventPoints }: Props) {
  const el = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MLMap | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [geo, setGeo] = useState<(GeoJSON.FeatureCollection & { bbox: number[] }) | null>(null)
  const [geoError, setGeoError] = useState<string | null>(null)
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null)
  const { regionId, regions, result, basemap, hillshade, showGroups, selectedCluster, compareCluster, selectedCatchment,
    setSelectedCatchment, showEvents } = useApp()
  const region = regions.find(r => r.id === regionId)

  // init map once
  useEffect(() => {
    if (!el.current || mapRef.current) return
    const map = new maplibregl.Map({ container: el.current, style: STYLE, center: [79.2, 30.2], zoom: 6.6, attributionControl: { compact: true }, maxPitch: 60 })
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-right')
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right')
    map.once('style.load', () => { // add data layers as soon as the style is ready (don't wait for basemap tiles)
      map.addSource('catchments', { type: 'geojson', data: { type: 'FeatureCollection', features: [] }, promoteId: 'catchment_id' })
      map.addLayer({ id: 'c-fill', type: 'fill', source: 'catchments', paint: { 'fill-color': '#3f7f6e', 'fill-opacity': 0.62 } })
      map.addLayer({ id: 'c-line', type: 'line', source: 'catchments', paint: { 'line-color': '#0b1015', 'line-width': 0.5, 'line-opacity': 0.75 } })
      map.addLayer({ id: 'c-sel', type: 'line', source: 'catchments', filter: ['==', ['get', 'catchment_id'], ''], paint: { 'line-color': '#ffffff', 'line-width': 2.4 } })
      map.addLayer({ id: 'labels', type: 'raster', source: 'labels', paint: { 'raster-opacity': 0.75 } })
      map.addSource('events', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addLayer({ id: 'ev-circle', type: 'circle', source: 'events', paint: {
        'circle-color': ['case', ['>', ['get', 'flash'], 0], '#ff4d6d', '#ffd166'],
        'circle-opacity': 0.85, 'circle-stroke-color': '#0b1015', 'circle-stroke-width': 1.2,
        'circle-radius': ['interpolate', ['linear'], ['sqrt', ['get', 'count']], 1, 5, 4, 13, 8, 22] } })
      map.addLayer({ id: 'ev-label', type: 'symbol', source: 'events', layout: { 'text-field': ['to-string', ['get', 'count']], 'text-size': 10, 'text-font': ['Noto Sans Regular'] }, paint: { 'text-color': '#0b1015' } })
      setLoaded(true)
    })
    map.on('mousemove', 'c-fill', e => {
      map.getCanvas().style.cursor = 'pointer'
      const p = e.features?.[0]?.properties as Record<string, number | string> | undefined
      if (p) setHover({ x: e.point.x, y: e.point.y, text: `${p.catchment_id} · ${Math.round(Number(p.elev_mean))} m${p.cluster !== undefined && Number(p.cluster) > -99 ? ` · ${p.cluster_name ?? ''}` : ''}` })
    })
    map.on('mouseleave', 'c-fill', () => { map.getCanvas().style.cursor = ''; setHover(null) })
    map.on('mousemove', 'ev-circle', e => {
      const p = e.features?.[0]?.properties as Record<string, string> | undefined
      if (p) setHover({ x: e.point.x, y: e.point.y, text: `${p.district}: ${p.count} recorded event(s)${Number(p.flash) ? `, ${p.flash} flash/cloudburst` : ''}` })
    })
    mapRef.current = map
    if (import.meta.env.DEV) (window as unknown as { __hsMap: MLMap }).__hsMap = map
    return () => { map.remove(); mapRef.current = null }
  }, [])

  // click handler depends on setter only
  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    const fn = (e: maplibregl.MapLayerMouseEvent) => {
      const id = e.features?.[0]?.properties?.catchment_id as string | undefined
      setSelectedCatchment(id ?? null)
    }
    map.on('click', 'c-fill', fn)
    return () => { map.off('click', 'c-fill', fn) }
  }, [loaded, setSelectedCatchment])

  // load region geometry
  useEffect(() => {
    if (!region) return
    setGeo(null); setGeoError(null)
    if (!region.prepared) { setGeoError('not-prepared'); return }
    api.catchments(region.id).then(setGeo).catch(e => setGeoError(e.message))
  }, [region?.id, region?.prepared]) // eslint-disable-line react-hooks/exhaustive-deps

  // push data (merge assignments)
  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded || !geo) return
    const assign = new Map((result?.region.id === regionId ? result.assignments : []).map(a => [a.catchment_id, a]))
    const names = new Map((result?.profiles ?? []).map(p => [p.cluster, p.name]))
    const features = geo.features.map(f => {
      const a = assign.get(String(f.properties?.catchment_id))
      return { ...f, properties: { ...f.properties, cluster: a ? a.cluster : -99, band: a ? a.baseline_band : -99, cluster_name: a ? names.get(a.cluster) : undefined } }
    }).filter(f => !result || result.region.id !== regionId || (f.properties.cluster as number) > -99)
    ;(map.getSource('catchments') as GeoJSONSource).setData({ type: 'FeatureCollection', features })
  }, [geo, result, regionId, loaded])

  // fit to region
  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded || !region) return
    const b = geo?.bbox ?? region.bbox
    const w = map.getContainer().clientWidth
    const h = map.getContainer().clientHeight
    // Leave room for the floating panels only when the viewport is wide enough.
    const side = w > 1100 ? 370 : w > 700 ? Math.round(w * 0.2) : 10
    const vert = h > 500 ? 50 : 10
    map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: { top: vert, bottom: vert, left: side, right: Math.round(side * 0.6) }, duration: 900 })
  }, [region?.id, geo, loaded]) // eslint-disable-line react-hooks/exhaustive-deps

  // keep the canvas sized to its container (panes can be hidden/resized)
  useEffect(() => {
    const map = mapRef.current
    if (!map || !el.current) return
    const ro = new ResizeObserver(() => map.resize())
    ro.observe(el.current)
    return () => ro.disconnect()
  }, [loaded])

  // styling
  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    const hasRun = !!result && result.region.id === regionId
    let color: maplibregl.ExpressionSpecification
    if (hasRun && showGroups && colorMode === 'clusters') {
      const m: (string | number)[] = []
      CLUSTER_COLORS.forEach((c, i) => m.push(i, c))
      color = ['match', ['get', 'cluster'], -1, NOISE_COLOR, ...m, '#444'] as unknown as maplibregl.ExpressionSpecification
    } else if (hasRun && colorMode === 'baseline') {
      color = ['match', ['get', 'band'], 0, BAND_COLORS[0], 1, BAND_COLORS[1], 2, BAND_COLORS[2], '#444'] as unknown as maplibregl.ExpressionSpecification
    } else {
      color = ['interpolate', ['linear'], ['get', 'elev_mean'], ...ELEV_STOPS.flat()] as unknown as maplibregl.ExpressionSpecification
    }
    map.setPaintProperty('c-fill', 'fill-color', color)
    const focus = [selectedCluster, compareCluster].filter((c): c is number => c !== null)
    const base = basemap === 'satellite' ? 0.55 : 0.68
    const opacity = focus.length && colorMode === 'clusters'
      ? ['case', ['in', ['get', 'cluster'], ['literal', focus]], 0.85, 0.08]
      : base
    map.setPaintProperty('c-fill', 'fill-opacity', opacity as maplibregl.ExpressionSpecification)
    map.setPaintProperty('c-line', 'line-opacity', showGroups || colorMode !== 'clusters' ? 0.75 : 0.3)
    map.setLayoutProperty('c-fill', 'visibility', showGroups ? 'visible' : 'none')
    map.setLayoutProperty('satellite', 'visibility', basemap === 'satellite' ? 'visible' : 'none')
    map.setLayoutProperty('dark', 'visibility', basemap === 'dark' ? 'visible' : 'none')
    map.setLayoutProperty('hillshade', 'visibility', hillshade ? 'visible' : 'none')
    map.setFilter('c-sel', ['==', ['get', 'catchment_id'], selectedCatchment ?? ''])
  }, [loaded, result, regionId, colorMode, showGroups, selectedCluster, compareCluster, basemap, hillshade, selectedCatchment])

  // events overlay
  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    const vis = showEvents && eventPoints ? 'visible' : 'none'
    ;(map.getSource('events') as GeoJSONSource).setData(eventPoints ?? { type: 'FeatureCollection', features: [] })
    map.setLayoutProperty('ev-circle', 'visibility', vis)
    map.setLayoutProperty('ev-label', 'visibility', vis)
  }, [loaded, eventPoints, showEvents])

  return (
    <div className="absolute inset-0" data-testid="map">
      <div ref={el} style={{ position: 'absolute', inset: 0 }} />
      {hover && (
        <div className="pointer-events-none absolute z-10 rounded-md bg-ink-900/95 px-2 py-1 font-mono text-[11px] text-ink-100 shadow-lg ring-1 ring-white/10"
          style={{ left: hover.x + 12, top: hover.y + 12 }}>{hover.text}</div>
      )}
      {geoError && geoError !== 'not-prepared' && (
        <div className="absolute left-1/2 top-16 z-10 -translate-x-1/2 rounded-md bg-red-900/80 px-3 py-2 text-xs text-red-100">Catchments unavailable: {geoError}</div>
      )}
    </div>
  )
}
