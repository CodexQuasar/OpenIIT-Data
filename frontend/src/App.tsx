import { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import AccountSearch from './pages/AccountSearch'
import AddressIntelligence from './pages/AddressIntelligence'
import MapView from './pages/MapView'
import FieldAgentView from './pages/FieldAgentView'
import Analytics from './pages/Analytics'
import ModelBenchmark from './pages/ModelBenchmark'
import Admin from './pages/Admin'

function App() {
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem('theme') === 'dark')

  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode)
  }, [darkMode])

  document.documentElement.classList.toggle('dark', localStorage.getItem('theme') === 'dark')

  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="search" element={<AccountSearch />} />
        <Route path="address/:accountId" element={<AddressIntelligence />} />
        <Route path="map/:accountId" element={<MapView />} />
        <Route path="field/:accountId" element={<FieldAgentView />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="benchmark" element={<ModelBenchmark />} />
        <Route path="admin" element={<Admin />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App