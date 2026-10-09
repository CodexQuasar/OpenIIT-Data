import { FormEvent, useEffect, useState } from 'react'
import { login, register } from '../services/api'

export default function Login() {
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem('theme') === 'dark')
  const [isRegistering, setIsRegistering] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode)
    localStorage.setItem('theme', darkMode ? 'dark' : 'light')
  }, [darkMode])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (isRegistering) {
        await register(username, password, fullName, email)
      }
      await login(username, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="relative min-h-screen bg-gray-50 dark:bg-gray-950 flex items-center justify-center px-4">
      <button
        type="button"
        className="absolute right-4 top-4 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 shadow-sm hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800"
        onClick={() => setDarkMode((value) => !value)}
        aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
      >
        {darkMode ? 'Light mode' : 'Dark mode'}
      </button>
      <form onSubmit={submit} className="card w-full max-w-md space-y-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Field Geocoder</h1>
          <p className="text-gray-600 dark:text-gray-400 mt-1">
            {isRegistering ? 'Create a field-agent account' : 'Sign in to continue'}
          </p>
        </div>
        {isRegistering && (
          <>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Full name
              <input className="input mt-1" value={fullName} onChange={(event) => setFullName(event.target.value)} />
            </label>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Email
              <input className="input mt-1" type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
            </label>
          </>
        )}
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
          Username
          <input className="input mt-1" required minLength={3} value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
          Password
          <input className="input mt-1" required minLength={8} type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
        <button className="btn-primary w-full" disabled={busy} type="submit">
          {busy ? 'Please wait...' : isRegistering ? 'Create account' : 'Sign in'}
        </button>
        <button
          className="w-full text-sm text-primary-700 hover:underline"
          type="button"
          onClick={() => { setIsRegistering(!isRegistering); setError(null) }}
        >
          {isRegistering ? 'Already have an account? Sign in' : 'Need an account? Register'}
        </button>
      </form>
    </main>
  )
}
