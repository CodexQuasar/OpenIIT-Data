import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { searchRealAccounts } from '../services/api'

export default function AccountSearch() {
  const [accounts, setAccounts] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const navigate = useNavigate()

  const fetchAccounts = async (search = '') => {
      try {
        setLoading(true)
        const data = await searchRealAccounts(search, 100)
        setAccounts(data)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch accounts')
      } finally {
        setLoading(false)
      }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => { void fetchAccounts() }, 0)
    return () => window.clearTimeout(timer)
  }, [])

  if (loading) {
    return <div className="text-center py-12">Loading accounts...</div>
  }

  if (error) {
    return <div className="text-center py-12 text-danger-600">Error: {error}</div>
  }

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-900 mb-6">Account Search</h2>
      <form className="card mb-6 flex gap-3" onSubmit={(event) => { event.preventDefault(); fetchAccounts(query.trim()) }}>
        <input
          className="input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search account ID, town, language, or address"
          aria-label="Search accounts"
        />
        <button className="btn-primary whitespace-nowrap" type="submit">Search</button>
        {query && <button className="btn-secondary whitespace-nowrap" type="button" onClick={() => { setQuery(''); fetchAccounts() }}>Clear</button>}
      </form>

      <div className="space-y-4">
        {accounts.map((account) => (
          <div key={account.account_id} className="card">
            <div className="flex justify-between items-start">
              <div>
                <p className="font-medium text-gray-900">{account.account_id}</p>
                <div className="flex gap-4 mt-2 text-sm text-gray-500">
                  <span>Town: {account.town_id}</span>
                  <span>Language: {account.preferred_language}</span>
                  <span>Portfolio: {account.portfolio}</span>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => navigate(`/address/${account.account_id}`)}
                  className="btn-secondary text-sm"
                >
                  Intelligence
                </button>
                <button
                  onClick={() => navigate(`/map/${account.account_id}`)}
                  className="btn-secondary text-sm"
                >
                  Map
                </button>
                <button
                  onClick={() => navigate(`/field/${account.account_id}`)}
                  className="btn-primary text-sm"
                >
                  Field View
                </button>
              </div>
            </div>
          </div>
        ))}

        {accounts.length === 0 && (
          <p className="text-center text-gray-500 py-8">No accounts found</p>
        )}
      </div>
    </div>
  )
}