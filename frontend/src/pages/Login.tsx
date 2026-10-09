import { FormEvent, useEffect, useState } from 'react'

export default function Login() {
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem('theme') === 'dark')

  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode)
    localStorage.setItem('theme', darkMode ? 'dark' : 'light')
  }, [darkMode])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
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
            Welcome to Field Geocoder
          </p>
        </div>
      </form>
    </main>
  )
}