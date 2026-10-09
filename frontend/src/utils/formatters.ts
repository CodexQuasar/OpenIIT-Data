import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDistance(meters: number): string {
  if (meters < 1000) {
    return `${Math.round(meters)}m`
  }
  return `${(meters / 1000).toFixed(1)}km`
}

export function formatConfidence(confidence: number): string {
  return `${Math.round(confidence * 100)}%`
}

export function formatDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export function formatDateTime(dateString: string): string {
  return new Date(dateString).toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function getConfidenceColor(confidence: number): string {
  if (confidence >= 0.85) return 'text-success-600'
  if (confidence >= 0.6) return 'text-warning-600'
  return 'text-danger-600'
}

export function getConfidenceBgColor(confidence: number): string {
  if (confidence >= 0.85) return 'bg-success-50'
  if (confidence >= 0.6) return 'bg-warning-50'
  return 'bg-danger-50'
}

export function getActionColor(action: string): string {
  switch (action) {
    case 'VISIT_DIRECTLY':
      return 'text-success-600 bg-success-50'
    case 'VERIFY_FIRST':
      return 'text-warning-600 bg-warning-50'
    case 'LOW_CONFIDENCE':
      return 'text-danger-600 bg-danger-50'
    default:
      return 'text-gray-600 bg-gray-50'
  }
}

export function getOutcomeColor(outcome: string): string {
  switch (outcome) {
    case 'SUCCESSFUL_CONTACT':
      return 'text-success-600'
    case 'PARTIAL_CONTACT':
      return 'text-warning-600'
    case 'FAILED_SEARCH':
    case 'ADDRESS_NOT_TRACEABLE':
    case 'WRONG_ADDRESS':
      return 'text-danger-600'
    default:
      return 'text-gray-600'
  }
}

export function getSourceColor(source: string): string {
  switch (source) {
    case 'HISTORICAL_VISIT':
      return 'bg-blue-100 text-blue-800'
    case 'NEARBY_ACCOUNT':
      return 'bg-green-100 text-green-800'
    case 'GEOCODER':
      return 'bg-purple-100 text-purple-800'
    case 'LANDMARK':
      return 'bg-orange-100 text-orange-800'
    case 'LOCALITY':
      return 'bg-yellow-100 text-yellow-800'
    case 'PINCODE':
      return 'bg-gray-100 text-gray-800'
    default:
      return 'bg-gray-100 text-gray-800'
  }
}