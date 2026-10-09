import axios from 'axios'
import type {
  Account,
  Visit,
  Prediction,
  PlaceCluster,
  Metrics,
  ModelInfo,
  GeocodeRequest,
  VisitCreateRequest,
} from '../types'

export interface AuthResponse {
  access_token: string
  token_type: string
  expires_in_hours: number
  user_id: string
  role: string
  tenant_id?: string
}

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  timeout: 30000,
})

// Add request interceptor to handle offline mode
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  if (!navigator.onLine && config.method !== 'get') {
    config.headers['X-Offline-Request'] = 'true'
  }
  return config
})
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      window.dispatchEvent(new Event('auth-expired'))
    }
    // Handle offline errors for non-GET requests
    if (!navigator.onLine && error.config && error.config.method !== 'get') {
      // Queue the request for later sync
      const { offlineQueue } = await import('../utils/offlineQueue');
      
      let visitData: Record<string, any> | null = null
      if (error.config.data) {
        try {
          visitData = typeof error.config.data === 'string'
            ? JSON.parse(error.config.data)
            : error.config.data
        } catch {
          visitData = null
        }
      }
      if (visitData) {
        await offlineQueue.queueVisit({
          accountId: visitData.account_id,
          agentId: visitData.agent_id,
          timestamp: visitData.timestamp,
          latitude: visitData.latitude,
          longitude: visitData.longitude,
          gpsAccuracy: visitData.gps_accuracy,
          outcome: visitData.outcome,
          dwellTime: visitData.dwell_time,
          remarks: visitData.remarks,
          trajectory: visitData.trajectory,
        });
      }
      
      // Return a mocked successful response for offline mode
      return {
        data: {
          ...visitData,
          visit_id: `offline_${Date.now()}`,
          queued: true,
          reliability_score: 0.5,
          integrity_score: 0.5,
        },
        status: 202,
        statusText: 'Queued for sync',
      };
    }
    
    return Promise.reject(error);
  }
);

export async function login(username: string, password: string): Promise<AuthResponse> {
  const { data } = await api.post<AuthResponse>('/auth/login', { username, password })
  localStorage.setItem('access_token', data.access_token)
  localStorage.setItem('user_role', data.role)
  window.dispatchEvent(new Event('authenticated'))
  return data
}

export async function register(
  username: string,
  password: string,
  fullName?: string,
  email?: string,
): Promise<void> {
  await api.post('/auth/register', {
    username,
    password,
    full_name: fullName || undefined,
    email: email || undefined,
    role: 'field_agent',
  })
}

export function logout(): void {
  localStorage.removeItem('access_token')
  localStorage.removeItem('user_role')
  window.dispatchEvent(new Event('auth-expired'))
}

// Geocoding
export async function geocodeAddress(request: GeocodeRequest): Promise<Prediction> {
  const { data } = await api.post<Prediction>('/geocode', request)
  return data
}

export async function geocodeBatch(requests: GeocodeRequest[]): Promise<Prediction[]> {
  const { data } = await api.post<Prediction[]>('/geocode/batch', { accounts: requests })
  return data
}

// Real dataset endpoints
export async function getRealAccounts(limit = 100, offset = 0) {
  const { data } = await api.get('/real/accounts', { params: { limit, offset } })
  return data
}

export async function searchRealAccounts(search: string, limit = 100, offset = 0) {
  const params: { search?: string; limit: number; offset: number } = { limit, offset }
  const normalizedSearch = search.trim()
  if (normalizedSearch) {
    params.search = normalizedSearch
  }
  const { data } = await api.get('/real/accounts', { params })
  return data
}

export async function getRealAccount(accountId: string) {
  const { data } = await api.get(`/real/accounts/${accountId}`)
  return data
}

export async function geocodeRealAddress(addressId: string) {
  const { data } = await api.get(`/real/addresses/${addressId}/geocode`)
  return data
}

export async function evaluateRealData() {
  const { data } = await api.get('/real/evaluate')
  return data
}

export async function evaluatePs3Experiments(split = 'train') {
  const { data } = await api.get('/real/evaluation/ps3', { params: { split } })
  return data
}

export async function getRealAddress(addressId: string) {
  const { data } = await api.get(`/real/addresses/${addressId}`)
  return data
}

export async function getRealTowns() {
  const { data } = await api.get('/real/towns')
  return data
}

export async function getRealLandmarks(townId?: string) {
  const { data } = await api.get('/real/landmarks', { params: { town_id: townId } })
  return data
}

// Visits
export async function createVisit(visit: VisitCreateRequest): Promise<Visit> {
  const { data } = await api.post<Visit>('/visits', visit)
  return data
}

export async function validateVisit(visit: VisitCreateRequest) {
  const { data } = await api.post('/visits/validate', { visit })
  return data
}

export async function getVisitsByAccount(accountId: string): Promise<Visit[]> {
  const { data } = await api.get<Visit[]>(`/visits/account/${accountId}`)
  return data
}

// Accounts
export async function createAccount(account: Partial<Account>): Promise<Account> {
  const { data } = await api.post<Account>('/accounts', account)
  return data
}

export async function getAccount(accountId: string): Promise<Account> {
  const { data } = await api.get<Account>(`/accounts/${accountId}`)
  return data
}

export async function searchAccounts(query: string): Promise<Account[]> {
  const { data } = await api.get<Account[]>('/accounts', { params: { search: query } })
  return data
}

export async function getAccountEvidence(accountId: string) {
  const { data } = await api.get(`/accounts/${accountId}/evidence`)
  return data
}

export async function getPredictionHistory(accountId: string): Promise<Prediction[]> {
  const { data } = await api.get<Prediction[]>(`/accounts/${accountId}/history`)
  return data
}

export async function getLatestPrediction(accountId: string): Promise<Prediction> {
  const { data } = await api.get<Prediction>(`/accounts/${accountId}/prediction`)
  return data
}

// Place Clusters
export async function getPlaceClusters(): Promise<PlaceCluster[]> {
  const { data } = await api.get<PlaceCluster[]>('/place-clusters')
  return data
}

// Metrics
export async function getMetrics(): Promise<Metrics> {
  const { data } = await api.get<Metrics>('/metrics')
  return data
}

export async function getConfidenceCalibration() {
  const { data } = await api.get('/metrics/confidence-calibration')
  return data
}

export async function getTerritoryMetrics() {
  const { data } = await api.get('/metrics/by-territory')
  return data
}

export async function getVisitPlan(limit = 100) {
  const { data } = await api.get('/planner/visits', { params: { limit } })
  return data
}

export async function getRpcLocationFeatures(accountId: string) {
  const { data } = await api.get(`/rpc/location-features/${accountId}`)
  return data
}

export async function getProductivityMetrics() {
  const { data } = await api.get('/metrics/productivity')
  return data
}

// Model
export async function getModelInfo(): Promise<ModelInfo> {
  const { data } = await api.get<ModelInfo>('/model/info')
  return data
}

export async function triggerModelRetrain(): Promise<{ status: string; message: string }> {
  const { data } = await api.post('/model/retrain')
  return data
}

// Health
export async function healthCheck() {
  const { data } = await api.get('/health')
  return data
}
