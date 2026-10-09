import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { getRealAccount, geocodeRealAddress, getRealAddress } from '../services/api'
import type { RealGeocodingResult } from '../types'
import { formatDistance, formatConfidence, getActionColor } from '../utils/formatters'

export default function FieldAgentView() {
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
        console.error('Failed to load field view:', err)
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

  if (loading) return <div className="text-center py-12">Loading...</div>
  if (!account) return <div className="text-center py-12">Account not found</div>

  const confidence = prediction?.confidence ?? 0

  const confidenceLevel = confidence >= 0.85
    ? 'HIGH CONFIDENCE'
    : confidence >= 0.6
    ? 'MEDIUM CONFIDENCE'
    : confidence > 0
    ? 'LOW CONFIDENCE'
    : 'NO PREDICTION'

  const statusBannerClass = confidence >= 0.85
    ? 'bg-success-50 border border-success-200 text-gray-900 dark:text-black'
    : confidence >= 0.6
    ? 'bg-warning-50 border border-warning-200 text-gray-900 dark:text-black'
    : 'bg-danger-50 border border-danger-200 text-gray-900 dark:text-black'

  return (
    <div className="max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold text-gray-900 mb-6">Field Agent View</h2>

      {/* Status Banner */}
      <div className={`rounded-lg p-4 mb-6 ${statusBannerClass}`}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-lg font-bold">{confidenceLevel}</p>
            {prediction && (
              <p className="text-sm mt-1">
                Radius: {prediction.confidence_radius_m !== null ? formatDistance(prediction.confidence_radius_m) : 'Unavailable'}
              </p>
            )}
          </div>
          {prediction && (
            <span className={`px-3 py-1 rounded-full text-sm font-medium ${getActionColor(prediction.recommended_action)}`}>
              {prediction.recommended_action.replace(/_/g, ' ')}
            </span>
          )}
        </div>
      </div>

      {/* Address */}
      {address && (
        <div className="card mb-4">
          <h3 className="text-sm font-medium text-gray-500 mb-1">Borrower Address</h3>
          <p className="text-gray-900">{address.address_text}</p>
        </div>
      )}

      {/* Prediction Details */}
      {prediction && (
        <div className="card mb-4">
          <h3 className="text-sm font-medium text-gray-500 mb-2">Predicted Location</h3>
          <p className="font-mono text-gray-900">
            {prediction.predicted_x != null && prediction.predicted_y != null
              ? `(${prediction.predicted_x.toFixed(1)}, ${prediction.predicted_y.toFixed(1)})`
              : 'No location candidate found'}
          </p>
          <div className="mt-3 flex gap-4 text-sm">
            <div>
              <span className="text-gray-500">Confidence: </span>
              <span className="font-medium">{formatConfidence(prediction.confidence)}</span>
            </div>
            <div>
              <span className="text-gray-500">Radius: </span>
              <span className="font-medium">
                {prediction.confidence_radius_m !== null ? formatDistance(prediction.confidence_radius_m) : 'Unavailable'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Directions based on landmarks */}
      {address && prediction && (
        <div className="card">
          <h3 className="text-sm font-medium text-gray-500 mb-3">Directions</h3>
          <div className="space-y-2">
            <div className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-primary-100 text-primary-700 flex items-center justify-center text-xs font-medium">
                1
              </span>
              <p className="text-gray-700 text-sm">
                Reach town center of {account.town_id}
              </p>
            </div>
            <div className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-primary-100 text-primary-700 flex items-center justify-center text-xs font-medium">
                2
              </span>
              <p className="text-gray-700 text-sm">
                Navigate to {prediction.predicted_x != null && prediction.predicted_y != null
                  ? `(${prediction.predicted_x.toFixed(0)}, ${prediction.predicted_y.toFixed(0)})`
                  : 'the address after verification'}
              </p>
            </div>
            {address.landmarks && address.landmarks.length > 0 && (
              <>
                {address.landmarks.slice(0, 3).map((landmark: any, i: number) => (
                  <div key={i} className="flex gap-3">
                    <span className="flex-shrink-0 w-6 h-6 rounded-full bg-primary-100 text-primary-700 flex items-center justify-center text-xs font-medium">
                      {i + 3}
                    </span>
                    <p className="text-gray-700 text-sm">
                      Look for {landmark.name} {landmark.x != null && landmark.y != null
                        ? `at (${landmark.x.toFixed(0)}, ${landmark.y.toFixed(0)})`
                        : 'near the recorded location'}
                    </p>
                  </div>
                ))}
              </>
            )}
            {prediction.error_m != null && (
              <div className="flex gap-3">
                <span className="flex-shrink-0 w-6 h-6 rounded-full bg-warning-100 text-warning-700 flex items-center justify-center text-xs font-medium">
                  !
                </span>
                <p className="text-gray-700 text-sm">
                  Note: Prediction error ~{prediction.error_m.toFixed(0)}m from surveyed location
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* No Prediction */}
      {!prediction && address && (
        <div className="card text-center py-8">
          <p className="text-gray-500">No prediction available for this address.</p>
          <p className="text-sm text-gray-400 mt-2">Run the geocoder to generate a prediction.</p>
          <button onClick={handleGeocode} className="btn-primary mt-4" disabled={loading}>
            {loading ? 'Geocoding...' : 'Run Geocoder'}
          </button>
        </div>
      )}

      {/* No Address */}
      {!address && (
        <div className="card text-center py-8">
          <p className="text-gray-500">No address available for this account.</p>
        </div>
      )}
    </div>
  )
}