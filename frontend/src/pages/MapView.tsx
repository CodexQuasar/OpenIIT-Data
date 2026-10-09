import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { getRealAccount, geocodeRealAddress, getRealAddress } from '../services/api'
import type { RealGeocodingResult } from '../types'
import { formatDistance, formatConfidence } from '../utils/formatters'
import GoogleMapPanel from '../components/GoogleMapPanel'

export default function MapView() {
  const { accountId } = useParams<{ accountId: string }>()
  const [account, setAccount] = useState<any>(null)
  const [address, setAddress] = useState<any>(null)
  const [prediction, setPrediction] = useState<RealGeocodingResult | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!accountId) return

    const fetchData = async () => {
      try {
        setLoading(true)
        const acc = await getRealAccount(accountId)
        setAccount(acc)

        if (acc.addresses && acc.addresses.length > 0) {
          const addr = await getRealAddress(acc.addresses[0].address_id)
          setAddress(addr)
        }
      } catch (err) {
        console.error('Failed to load map data:', err)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [accountId])

  const handleGeocode = async () => {
    if (!address) return
    try {
      setLoading(true)
      const result = await geocodeRealAddress(address.address_id)
      setPrediction(result)
    } catch (err) {
      console.error('Geocoding failed:', err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="text-center py-12">Loading map...</div>
  if (!account) return <div className="text-center py-12">Account not found</div>

  // Prepare scatter plot data
  const visitData = address?.visits?.map((v: any) => ({
    x: v.checkin_x,
    y: v.checkin_y,
    outcome: v.outcome,
    visit_id: v.visit_id,
  })) || []

  const predictionData = prediction ? [{
    x: prediction.predicted_x,
    y: prediction.predicted_y,
    type: 'prediction',
  }] : []

  const groundTruthData = address?.surveyed ? [{
    x: address.surveyed.x,
    y: address.surveyed.y,
    type: 'ground_truth',
  }] : []

  const baselineData = address?.baseline_geocode ? [{
    x: address.baseline_geocode.x,
    y: address.baseline_geocode.y,
    type: 'baseline',
  }] : []

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold text-gray-900">Map View</h2>
        <button onClick={handleGeocode} className="btn-primary" disabled={loading || !address}>
          {loading ? 'Geocoding...' : 'Run Geocoder'}
        </button>
      </div>

      <div className="card">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Spatial Visualization (Local Coordinates)</h3>
        <div className="h-96">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" dataKey="x" name="X" unit="m" />
              <YAxis type="number" dataKey="y" name="Y" unit="m" />
              <Tooltip cursor={{ strokeDasharray: '3 3' }} />
              <Legend />
              <Scatter name="Visits" data={visitData} fill="#93c5fd" />
              <Scatter name="Prediction" data={predictionData} fill="#22c55e" shape="star" />
              <Scatter name="Ground Truth" data={groundTruthData} fill="#ef4444" shape="diamond" />
              <Scatter name="Baseline" data={baselineData} fill="#f59e0b" shape="square" />
            </ScatterChart>
          </ResponsiveContainer>
        </div>

        <div className="card mt-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Google Maps (WGS84 operational view)</h3>
          <GoogleMapPanel
            latitude={account.latitude}
            longitude={account.longitude}
            radiusM={account.confidence_radius_m ?? undefined}
          />
        </div>
      </div>

      {/* Legend */}
      <div className="mt-4 flex gap-6 text-sm">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded-full bg-blue-300" />
          <span>Historical Visits</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded-full bg-green-500" />
          <span>Prediction</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded-full bg-red-500" />
          <span>Ground Truth</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded-full bg-yellow-500" />
          <span>Baseline Geocode</span>
        </div>
      </div>

      {/* Prediction Details */}
      {prediction && (
        <div className="mt-6 card">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Prediction Details</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-sm text-gray-500">Confidence</p>
              <p className="text-xl font-bold">{formatConfidence(prediction.confidence)}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Radius</p>
              <p className="text-xl font-bold">
                {prediction.confidence_radius_m !== null ? formatDistance(prediction.confidence_radius_m) : 'Unavailable'}
              </p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Predicted</p>
              <p className="font-mono">
                {prediction.predicted_x != null && prediction.predicted_y != null
                  ? `(${prediction.predicted_x.toFixed(1)}, ${prediction.predicted_y.toFixed(1)})`
                  : 'No location candidate found'}
              </p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Error</p>
              <p className="text-xl font-bold text-danger-600">
                {prediction.error_m != null ? `${prediction.error_m.toFixed(1)}m` : 'Unavailable'}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}