import { useState, useEffect } from 'react'
import { getRealAccounts, evaluateRealData, getRealTowns } from '../services/api'
import type { RealEvaluationResult } from '../types'

export default function Dashboard() {
  const [accounts, setAccounts] = useState<any[]>([])
  const [towns, setTowns] = useState<any[]>([])
  const [evaluation, setEvaluation] = useState<RealEvaluationResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true)
        const [accData, townData, evalData] = await Promise.all([
          getRealAccounts(10),
          getRealTowns(),
          evaluateRealData(),
        ])
        setAccounts(accData)
        setTowns(townData)
        setEvaluation(evalData)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch data')
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [])

  if (loading) {
    return <div className="text-center py-12">Loading dashboard...</div>
  }

  if (error) {
    return <div className="text-center py-12 text-danger-600">Error: {error}</div>
  }

  const stats = [
    { label: 'Total Accounts', value: accounts.length },
    { label: 'Towns', value: towns.length },
    { label: 'Surveyed Addresses', value: evaluation?.total_evaluated || 0 },
    { label: 'Median Error', value: evaluation ? `${evaluation.median_error_m.toFixed(1)}m` : 'N/A' },
    { label: 'P90 Error', value: evaluation ? `${evaluation.p90_error_m.toFixed(1)}m` : 'N/A' },
    { label: 'Within 100m', value: evaluation ? `${(evaluation.within_100m * 100).toFixed(1)}%` : 'N/A' },
    { label: 'Within 250m', value: evaluation ? `${(evaluation.within_250m * 100).toFixed(1)}%` : 'N/A' },
    { label: 'Within 500m', value: evaluation ? `${(evaluation.within_500m * 100).toFixed(1)}%` : 'N/A' },
  ]

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-900 mb-6">Dashboard</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {stats.map((stat) => (
          <div key={stat.label} className="card">
            <p className="text-sm text-gray-500">{stat.label}</p>
            <p className="text-2xl font-bold text-gray-900 mt-1">{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Towns */}
      {towns.length > 0 && (
        <div className="mt-8">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Towns</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {towns.map((town) => (
              <div key={town.town_id} className="card">
                <p className="font-medium text-gray-900">{town.town_name}</p>
                <p className="text-sm text-gray-500 mt-1">Style: {town.address_style}</p>
                <p className="text-sm text-gray-500">Radius: {town.approx_radius_m}m</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Evaluation Results */}
      {evaluation && (
        <div className="mt-8">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Evaluation Results (Surveyed Addresses)</h3>
          <div className="card">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <p className="text-sm text-gray-500">Median Error</p>
                <p className="text-xl font-bold text-primary-600">{(evaluation.median_error_m ?? 0).toFixed(1)}m</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Mean Error</p>
                <p className="text-xl font-bold text-primary-600">{(evaluation.mean_error_m ?? 0).toFixed(1)}m</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">P90 Error</p>
                <p className="text-xl font-bold text-warning-600">{(evaluation.p90_error_m ?? 0).toFixed(1)}m</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">P95 Error</p>
                <p className="text-xl font-bold text-danger-600">{(evaluation.p95_error_m ?? 0).toFixed(1)}m</p>
              </div>
            </div>
            <div className="mt-4 pt-4 border-t">
              <p className="text-sm text-gray-500 mb-2">Accuracy at Distance Thresholds</p>
              <div className="flex gap-4">
                <div className="flex-1 bg-success-50 rounded p-2 text-center">
                  <p className="text-lg font-bold text-success-600">{((evaluation.within_50m ?? 0) * 100).toFixed(1)}%</p>
                  <p className="text-xs text-gray-500">Within 50m</p>
                </div>
                <div className="flex-1 bg-success-50 rounded p-2 text-center">
                  <p className="text-lg font-bold text-success-600">{((evaluation.within_100m ?? 0) * 100).toFixed(1)}%</p>
                  <p className="text-xs text-gray-500">Within 100m</p>
                </div>
                <div className="flex-1 bg-warning-50 rounded p-2 text-center">
                  <p className="text-lg font-bold text-warning-600">{((evaluation.within_250m ?? 0) * 100).toFixed(1)}%</p>
                  <p className="text-xs text-gray-500">Within 250m</p>
                </div>
                <div className="flex-1 bg-warning-50 rounded p-2 text-center">
                  <p className="text-lg font-bold text-warning-600">{((evaluation.within_500m ?? 0) * 100).toFixed(1)}%</p>
                  <p className="text-xs text-gray-500">Within 500m</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}