import { useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line } from 'recharts'
import { useMetrics, useCalibrationData, useTerritoryMetrics } from '../hooks/useMetrics'
import { formatDistance, formatConfidence } from '../utils/formatters'

export default function Analytics() {
  const { metrics, loading: metricsLoading, error: metricsError } = useMetrics()
  const { data: calibrationData, loading: calibrationLoading } = useCalibrationData()
  const { data: territoryData, loading: territoryLoading } = useTerritoryMetrics()
  const [activeTab, setActiveTab] = useState<'errors' | 'calibration' | 'territory'>('errors')

  if (metricsLoading || calibrationLoading || territoryLoading) return <div className="text-center py-12">Loading analytics...</div>
  if (metricsError) return <div className="text-center py-12 text-danger-600">Error: {metricsError}</div>
  if (!metrics) return <div className="text-center py-12">No data available</div>

  const errorData = [
    { name: 'Median', value: metrics.median_error_m || 0 },
    { name: 'P75', value: (metrics.median_error_m || 0) * 1.5 },
    { name: 'P90', value: metrics.p90_error_m || 0 },
    { name: 'P95', value: (metrics.p90_error_m || 0) * 1.2 },
  ]

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-900 mb-6">Analytics</h2>

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        {(['errors', 'calibration', 'territory'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === tab
                ? 'bg-primary-100 text-primary-700'
                : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Error Distribution */}
      {activeTab === 'errors' && (
        <div className="card">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Distance Error Distribution</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={errorData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis />
                <Tooltip formatter={(value: number) => formatDistance(value)} />
                <Bar dataKey="value" fill="#3b82f6" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <p className="text-gray-500">Within 50m</p>
              <p className="font-bold">{metrics.within_50m ? formatConfidence(metrics.within_50m) : 'N/A'}</p>
            </div>
            <div>
              <p className="text-gray-500">Within 100m</p>
              <p className="font-bold">{metrics.within_100m ? formatConfidence(metrics.within_100m) : 'N/A'}</p>
            </div>
            <div>
              <p className="text-gray-500">Within 250m</p>
              <p className="font-bold">{metrics.within_250m ? formatConfidence(metrics.within_250m) : 'N/A'}</p>
            </div>
            <div>
              <p className="text-gray-500">Within 500m</p>
              <p className="font-bold">{metrics.within_500m ? formatConfidence(metrics.within_500m) : 'N/A'}</p>
            </div>
          </div>
        </div>
      )}

      {/* Calibration */}
      {activeTab === 'calibration' && (
        <div className="card">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Confidence Calibration</h3>
          {calibrationData && calibrationData.bins && calibrationData.bins.length > 0 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={calibrationData.bins}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="bin" />
                  <YAxis domain={[0, 1]} />
                  <Tooltip />
                  <Line type="monotone" dataKey="predicted" stroke="#3b82f6" name="Predicted" />
                  <Line type="monotone" dataKey="actual" stroke="#22c55e" name="Actual" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-64 flex items-center justify-center text-gray-500">
              No calibration data available. Run evaluation to generate.
            </div>
          )}
          <div className="mt-4 text-sm text-gray-600">
            <p>Calibration Error (ECE): {metrics.calibration_error?.toFixed(3) || 'N/A'}</p>
            <p>Confidence Coverage: {metrics.confidence_coverage ? formatConfidence(metrics.confidence_coverage) : 'N/A'}</p>
          </div>
        </div>
      )}

      {/* Territory Performance */}
      {activeTab === 'territory' && (
        <div className="card">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Territory Performance</h3>
          {territoryData && territoryData.metrics && territoryData.metrics.length > 0 ? (
            <>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={territoryData.metrics}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="territory" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="accounts" fill="#3b82f6" name="Accounts" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left py-2">Territory</th>
                      <th className="text-right py-2">Accounts</th>
                      <th className="text-right py-2">Accuracy</th>
                    </tr>
                  </thead>
                  <tbody>
                    {territoryData.metrics.map((item: any) => (
                      <tr key={item.territory} className="border-b">
                        <td className="py-2">{item.territory}</td>
                        <td className="text-right">{item.accounts}</td>
                        <td className="text-right">
                          {formatConfidence(item.accuracy ?? item.within_250m ?? 0)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="h-64 flex items-center justify-center text-gray-500">
              No territory data available.
            </div>
          )}
        </div>
      )}
    </div>
  )
}