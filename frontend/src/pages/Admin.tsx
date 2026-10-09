import { useEffect, useState } from 'react'
import { getModelInfo, triggerModelRetrain } from '../services/api'
import type { ModelInfo } from '../types'

export default function Admin() {
  const isAdmin = localStorage.getItem('user_role') === 'admin'
  const [model, setModel] = useState<ModelInfo | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getModelInfo().then(setModel).catch((err) => setError(err instanceof Error ? err.message : 'Failed to load model info'))
  }, [])

  if (!isAdmin) {
    return <div className="text-center py-12 text-danger-600">Admin access required.</div>
  }

  const retrain = async () => {
    setMessage(null)
    setError(null)
    try {
      const result = await triggerModelRetrain()
      setMessage(result.message)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Retraining request failed')
    }
  }

  return (
    <div className="max-w-3xl">
      <h2 className="text-2xl font-bold text-gray-900 mb-6">Admin Panel</h2>
      <div className="card space-y-4">
        <h3 className="text-lg font-semibold text-gray-900">Model operations</h3>
        {model ? (
          <dl className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
            <div><dt className="text-gray-500">Model</dt><dd className="font-medium">{model.model_name}</dd></div>
            <div><dt className="text-gray-500">Version</dt><dd className="font-medium">{model.model_version}</dd></div>
            <div><dt className="text-gray-500">Feature version</dt><dd className="font-medium">{model.feature_version}</dd></div>
            <div><dt className="text-gray-500">Embedding model</dt><dd className="font-medium">{model.embedding_model}</dd></div>
          </dl>
        ) : <p className="text-gray-500">Loading model information...</p>}
        <button className="btn-primary" type="button" onClick={retrain}>Queue model retraining</button>
        {message && <p className="text-sm text-success-700">{message}</p>}
        {error && <p className="text-sm text-danger-700">{error}</p>}
      </div>
      <p className="text-sm text-gray-500 mt-4">
        User management, tenant policies, audit review, retention configuration, and deployment controls should be connected here for a lender production deployment.
      </p>
    </div>
  )
}
