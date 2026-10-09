import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { getRealAccount, geocodeRealAddress, getRealAddress } from '../services/api'
import type { RealGeocodingResult } from '../types'
import { formatDistance, formatConfidence, getConfidenceColor, getActionColor } from '../utils/formatters'

export default function AddressIntelligence() {
  const { accountId } = useParams<{ accountId: string }>()
  const [account, setAccount] = useState<any>(null)
  const [address, setAddress] = useState<any>(null)
  const [prediction, setPrediction] = useState<RealGeocodingResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!accountId) return

    const fetchData = async () => {
      try {
        setLoading(true)
        const acc = await getRealAccount(accountId)
        setAccount(acc)

        // Get first address
        if (acc.addresses && acc.addresses.length > 0) {
          const addr = await getRealAddress(acc.addresses[0].address_id)
          setAddress(addr)
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load data')
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
      setError(err instanceof Error ? err.message : 'Geocoding failed')
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="text-center py-12">Loading...</div>
  if (error) return <div className="text-center py-12 text-danger-600">Error: {error}</div>
  if (!account) return <div className="text-center py-12">Account not found</div>

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold text-gray-900">Address Intelligence</h2>
        <button onClick={handleGeocode} className="btn-primary" disabled={loading || !address}>
          {loading ? 'Geocoding...' : 'Run Geocoder'}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Address Info */}
        {address && (
          <div className="card">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Address</h3>
            <div className="space-y-3">
              <div>
                <p className="text-sm text-gray-500">Address ID</p>
                <p className="text-gray-900">{address.address_id}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Type</p>
                <p className="text-gray-900">{address.address_type}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Address Text</p>
                <p className="text-gray-900">{address.address_text}</p>
              </div>
              <div className="flex gap-4 text-sm">
                <span className="text-gray-600">Town: {address.town_id}</span>
              </div>
            </div>
          </div>
        )}

        {/* Prediction */}
        {prediction && (
          <div className="card">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Prediction</h3>
            <div className="space-y-3">
              <div className="flex items-center gap-4">
                <div>
                  <p className="text-sm text-gray-500">Confidence</p>
                  <p className={`text-2xl font-bold ${getConfidenceColor(prediction.confidence)}`}>
                    {formatConfidence(prediction.confidence)}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-gray-500">Radius</p>
                  <p className="text-2xl font-bold text-gray-900">
                    {prediction.confidence_radius_m !== null
                      ? formatDistance(prediction.confidence_radius_m)
                      : 'Unavailable'}
                  </p>
                </div>
              </div>
              <div>
                <p className="text-sm text-gray-500">Recommended Action</p>
                <span className={`inline-block px-3 py-1 rounded-full text-sm font-medium ${getActionColor(prediction.recommended_action)}`}>
                  {prediction.recommended_action.replace(/_/g, ' ')}
                </span>
              </div>
              <div>
                <p className="text-sm text-gray-500">Predicted Coordinates</p>
                <p className="text-gray-900 font-mono">
                  {prediction.predicted_x !== null && prediction.predicted_y !== null
                    ? `(${prediction.predicted_x.toFixed(1)}, ${prediction.predicted_y.toFixed(1)})`
                    : 'No location candidate found'}
                </p>
              </div>
              {prediction.error_m !== undefined && prediction.error_m !== null && (
                <div>
                  <p className="text-sm text-gray-500">Error from Ground Truth</p>
                  <p className="text-gray-900 font-mono">
                    {prediction.error_m.toFixed(1)}m
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Evidence */}
        {address && address.visits && (
          <div className="card lg:col-span-2">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Evidence</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
              <div className="bg-gray-50 rounded-lg p-4">
                <p className="text-sm text-gray-500">Total Visits</p>
                <p className="text-xl font-bold">{address.visits.length}</p>
              </div>
              <div className="bg-success-50 rounded-lg p-4">
                <p className="text-sm text-gray-500">Successful</p>
                <p className="text-xl font-bold text-success-600">
                  {address.visits.filter((v: any) => v.outcome === 'met_borrower' || v.outcome === 'met_family').length}
                </p>
              </div>
              <div className="bg-danger-50 rounded-lg p-4">
                <p className="text-sm text-gray-500">Failed</p>
                <p className="text-xl font-bold text-danger-600">
                  {address.visits.filter((v: any) => v.outcome === 'address_not_traceable' || v.outcome === 'locked_premises').length}
                </p>
              </div>
            </div>

            {prediction?.evidence && (
              <div className="border-t pt-4">
                <h4 className="font-medium text-gray-900 mb-2">Why this location?</h4>
                <ul className="space-y-1">
                  {prediction.evidence.strongest_evidence.map((item, i) => (
                    <li key={i} className="text-sm text-gray-600 flex items-center gap-2">
                      <span className="text-success-500">✓</span> {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Baseline Geocode */}
        {address?.baseline_geocode && (
          <div className="card lg:col-span-2">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Baseline Geocode</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-sm text-gray-500">Coordinates</p>
                <p className="font-mono">({address.baseline_geocode.x.toFixed(1)}, {address.baseline_geocode.y.toFixed(1)})</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Precision</p>
                <p className="capitalize">{address.baseline_geocode.precision}</p>
              </div>
            </div>
          </div>
        )}

        {/* Surveyed Ground Truth */}
        {address?.surveyed && (
          <div className="card lg:col-span-2">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Surveyed Ground Truth</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-sm text-gray-500">Coordinates</p>
                <p className="font-mono">({address.surveyed.x.toFixed(1)}, {address.surveyed.y.toFixed(1)})</p>
              </div>
              {prediction && (
                <div>
                  <p className="text-sm text-gray-500">Prediction Error</p>
                  <p className="font-mono text-lg font-bold">
                    {prediction.error_m?.toFixed(1)}m
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}