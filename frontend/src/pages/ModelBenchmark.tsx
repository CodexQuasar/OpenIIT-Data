import { useState, useEffect } from 'react'
import { evaluateRealData, evaluatePs3Experiments, getConfidenceCalibration } from '../services/api'
import { formatDistance, formatConfidence } from '../utils/formatters'

interface ProposedMetrics {
  median_error_m: number
  p90_error_m: number
  within_50m: number
  within_100m: number
  within_250m: number
  within_500m: number
  within_1000m: number
  median_confidence: number | null
  calibration_ece: number | null
}

export default function ModelBenchmark() {
  const [proposedMetrics, setProposedMetrics] = useState<ProposedMetrics | null>(null)
  const [baseline, setBaseline] = useState<{median_error_m: number; p90_error_m: number} | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [evaluation, setEvaluation] = useState<any>(null)

  useEffect(() => {
    const fetchBenchmark = async () => {
      try {
        setLoading(true)
        const [result, calibration, experiments] = await Promise.all([
          evaluateRealData(),
          getConfidenceCalibration(),
          evaluatePs3Experiments(),
        ])
        const calibrationBins = calibration.bins || []
        const sampleCount = calibrationBins.reduce((sum: number, bin: { count: number }) => sum + bin.count, 0)
        const medianConfidence = sampleCount
          ? calibrationBins.reduce((sum: number, bin: { predicted: number; count: number }) => sum + bin.predicted * bin.count, 0) / sampleCount
          : null
        setProposedMetrics({
          median_error_m: result.median_error_m ?? 0,
          p90_error_m: result.p90_error_m ?? 0,
          within_50m: result.within_50m ?? 0,
          within_100m: result.within_100m ?? 0,
          within_250m: result.within_250m ?? 0,
          within_500m: result.within_500m ?? 0,
          within_1000m: result.within_1000m ?? 0,
          median_confidence: medianConfidence,
          calibration_ece: calibration.overall_ece ?? null,
        })
        setBaseline(experiments.baselines?.commercial_geocoder ?? result.baselines?.commercial_geocoder ?? null)
        setEvaluation(experiments)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch benchmark data')
      } finally {
        setLoading(false)
      }
    }

    fetchBenchmark()
  }, [])

  if (loading) return <div className="text-center py-12">Loading benchmark...</div>
  if (error) return <div className="text-center py-12 text-danger-600">Error: {error}</div>
  if (!proposedMetrics) return <div className="text-center py-12">No benchmark data available</div>

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-900 mb-6">Model Benchmark</h2>

      <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-lg">
        <p className="text-amber-800 text-sm">
          <strong>Note:</strong> This page shows the proposed model's real evaluation results from the CreditNirvana dataset.
          Baselines are shown only when computed from the same surveyed-address evaluation run; unavailable metrics are not fabricated.
        </p>
      </div>

      {/* Proposed Model Metrics */}
      <div className="space-y-6">
        <div className="card">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Proposed Model - Real Dataset Evaluation</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-4 bg-blue-50 rounded-lg">
              <p className="text-blue-600 text-sm font-medium">Median Error</p>
              <p className="text-2xl font-bold text-blue-900">{formatDistance(proposedMetrics.median_error_m)}</p>
            </div>
            <div className="p-4 bg-green-50 rounded-lg">
              <p className="text-green-600 text-sm font-medium">P90 Error</p>
              <p className="text-2xl font-bold text-green-900">{formatDistance(proposedMetrics.p90_error_m)}</p>
            </div>
            <div className="p-4 bg-purple-50 rounded-lg">
              <p className="text-purple-600 text-sm font-medium">Within 250m</p>
              <p className="text-2xl font-bold text-purple-900">{formatConfidence(proposedMetrics.within_250m)}</p>
            </div>
            <div className="p-4 bg-orange-50 rounded-lg">
              <p className="text-orange-600 text-sm font-medium">Within 500m</p>
              <p className="text-2xl font-bold text-orange-900">{formatConfidence(proposedMetrics.within_500m)}</p>
            </div>
          </div>
        </div>

        <div className="card overflow-x-auto">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Coverage Metrics</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b">
                <th className="text-left py-2">Metric</th>
                <th className="text-right py-2">Value</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b">
                <td className="py-2">Within 50m</td>
                <td className="text-right">{formatConfidence(proposedMetrics.within_50m)}</td>
              </tr>
              <tr className="border-b">
                <td className="py-2">Within 100m</td>
                <td className="text-right">{formatConfidence(proposedMetrics.within_100m)}</td>
              </tr>
              <tr className="border-b">
                <td className="py-2">Within 250m</td>
                <td className="text-right">{formatConfidence(proposedMetrics.within_250m)}</td>
              </tr>
              <tr className="border-b">
                <td className="py-2">Within 500m</td>
                <td className="text-right">{formatConfidence(proposedMetrics.within_500m)}</td>
              </tr>
              <tr className="border-b">
                <td className="py-2">Within 1000m</td>
                <td className="text-right">{formatConfidence(proposedMetrics.within_1000m)}</td>
              </tr>
              <tr className="border-b">
                <td className="py-2">Median Error</td>
                <td className="text-right">{formatDistance(proposedMetrics.median_error_m)}</td>
              </tr>
              <tr className="border-b">
                <td className="py-2">P90 Error</td>
                <td className="text-right">{formatDistance(proposedMetrics.p90_error_m)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Calibration & Confidence</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-gray-600 text-sm font-medium">Median Confidence</p>
              <p className="text-xl font-bold text-gray-900">{proposedMetrics.median_confidence == null ? 'N/A' : formatConfidence(proposedMetrics.median_confidence)}</p>
            </div>
            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-gray-600 text-sm font-medium">Calibration Error (ECE)</p>
              <p className="text-xl font-bold text-gray-900">{proposedMetrics.calibration_ece == null ? 'N/A' : proposedMetrics.calibration_ece.toFixed(3)}</p>
            </div>
          </div>
        </div>

        {baseline && <div className="card">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Measured Baseline</h3>
          <p>Commercial geocoder median error: {formatDistance(baseline.median_error_m)}</p>
          <p>Commercial geocoder P90 error: {formatDistance(baseline.p90_error_m)}</p>
        </div>}

        {evaluation && <div className="card space-y-4">
          <h3 className="text-lg font-semibold text-gray-900">Versioned Evaluation Run</h3>
          <p className="text-sm text-gray-600">{evaluation.run?.run_id} · {evaluation.run?.config?.artifact_version}</p>
          <div>
            <h4 className="font-medium mb-2">Baseline comparisons</h4>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-sm">
              {Object.entries(evaluation.baselines || {}).map(([name, metrics]: [string, any]) => (
                <div key={name} className="p-3 bg-gray-50 rounded">
                  <p className="font-medium">{name.replace(/_/g, ' ')}</p>
                  <p>Median: {metrics.median_error_m == null ? 'N/A' : formatDistance(metrics.median_error_m)}</p>
                  <p>Coverage: {metrics.coverage_rate == null ? 'N/A' : formatConfidence(metrics.coverage_rate)}</p>
                </div>
              ))}
            </div>
          </div>
          <div>
            <h4 className="font-medium mb-2">Ablations</h4>
            <p className="text-sm text-gray-700">
              {Object.entries(evaluation.ablations || {}).map(([name, value]: [string, any]) =>
                `${name.replace(/_/g, ' ')}: ${value.status === 'not_estimable' ? 'not estimable' : formatDistance(value.median_error_m)}`
              ).join(' · ')}
            </p>
          </div>
          <div>
            <h4 className="font-medium mb-2">Performance radar</h4>
            <p className="text-sm text-gray-700">
              {Object.entries(evaluation.radar?.metrics || {}).map(([name, value]) =>
                `${name}: ${typeof value === 'number' ? value.toFixed(3) : 'N/A'}`
              ).join(' · ')}
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div>
              <h4 className="font-medium mb-1">Geography holdout</h4>
              <p>{evaluation.splits?.geography_holdout?.holdout_towns?.join(', ') || 'N/A'} · {evaluation.splits?.geography_holdout?.status}</p>
            </div>
            <div>
              <h4 className="font-medium mb-1">Account-level temporal split</h4>
              <p>{evaluation.splits?.account_level_split?.status} · overlap {evaluation.splits?.account_level_split?.overlap_count ?? 'N/A'}</p>
            </div>
          </div>
          <div>
            <h4 className="font-medium mb-1">Counterfactual evaluation</h4>
            <p className="text-sm text-gray-700">
              {evaluation.counterfactual?.status === 'not_estimable'
                ? `Not estimable: ${evaluation.counterfactual.reason}`
                : 'Propensity-weighted and doubly robust diagnostics available.'}
            </p>
          </div>
        </div>}
      </div>
    </div>
  )
}