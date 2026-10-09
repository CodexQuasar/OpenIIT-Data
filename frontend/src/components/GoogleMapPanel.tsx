import { useEffect, useRef, useState } from 'react'
import { importLibrary, setOptions } from '@googlemaps/js-api-loader'

interface GoogleMapPanelProps {
  latitude?: number
  longitude?: number
  radiusM?: number
}

export default function GoogleMapPanel({ latitude, longitude, radiusM }: GoogleMapPanelProps) {
  const mapElement = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY

  useEffect(() => {
    if (!apiKey || latitude === undefined || longitude === undefined || !mapElement.current) return

    let cancelled = false
    setOptions({ key: apiKey, v: 'weekly' })
    Promise.all([importLibrary('maps'), importLibrary('marker')]).then(([{ Map, Circle }, { AdvancedMarkerElement }]) => {
      if (cancelled || !mapElement.current) return
      const center = { lat: latitude, lng: longitude }
      const map = new Map(mapElement.current, {
        center,
        zoom: 17,
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: true,
      })
      new AdvancedMarkerElement({ map, position: center, title: 'Operational location' })
      if (radiusM && radiusM > 0) {
        new Circle({
          map,
          center,
          radius: radiusM,
          fillColor: '#2563eb',
          fillOpacity: 0.12,
          strokeColor: '#2563eb',
          strokeOpacity: 0.7,
          strokeWeight: 1,
        })
      }
    }).catch(() => {
      if (!cancelled) setError('Google Maps could not be loaded. Check the API key, billing, and allowed origins.')
    })

    return () => {
      cancelled = true
    }
  }, [apiKey, latitude, longitude, radiusM])

  if (!apiKey) {
    return <p className="text-sm text-gray-500">Google Maps is disabled. Set VITE_GOOGLE_MAPS_API_KEY to enable it.</p>
  }
  if (latitude === undefined || longitude === undefined) {
    return <p className="text-sm text-gray-500">Google Maps requires WGS84 latitude and longitude. Projected PS3 coordinates are shown in the chart above.</p>
  }
  if (error) return <p className="text-sm text-danger-600">{error}</p>
  return <div ref={mapElement} className="h-96 w-full rounded-lg" aria-label="Google map" />
}
