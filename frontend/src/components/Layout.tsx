import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { cn } from '../utils/formatters'
import { OfflineIndicator } from './OfflineIndicator'
import { logout } from '../services/api'

const navItems = [
  { path: '/', label: 'Dashboard' },
  { path: '/search', label: 'Account Search' },
  { path: '/analytics', label: 'Analytics' },
  { path: '/benchmark', label: 'Model Benchmark' },
]

export default function Layout() {
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem('theme') === 'dark')
  const isAdmin = localStorage.getItem('user_role') === 'admin'

  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode)
    localStorage.setItem('theme', darkMode ? 'dark' : 'light')
  }, [darkMode])

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <nav className="bg-white border-b border-gray-200 dark:bg-gray-900 dark:border-gray-700">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center">
              <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">Field Geocoder</h1>
            </div>
            <div className="flex items-center space-x-2 overflow-x-auto">
              {navItems.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    cn(
                      'whitespace-nowrap px-3 py-2 rounded-md text-sm font-medium transition-colors',
                      isActive
                        ? 'bg-primary-100 text-primary-700'
                        : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                    )
                  }
                >
                  {item.label}
                </NavLink>
              ))}
              {isAdmin && <NavLink to="/admin" className="whitespace-nowrap px-3 py-2 rounded-md text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100">Admin</NavLink>}
              <button
                className="rounded-md px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-white"
                onClick={() => setDarkMode((value) => !value)}
                aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
                title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
              >
                {darkMode ? 'Light' : 'Dark'}
              </button>
              <button className="text-sm text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white" onClick={logout}>Sign out</button>
            </div>
          </div>
        </div>
      </nav>
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>
      <OfflineIndicator />
    </div>
  )
}