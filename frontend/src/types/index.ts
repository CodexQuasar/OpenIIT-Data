export interface Account {
  account_id: string
  address: string
  normalized_address?: NormalizedAddress
  language?: string
  pincode?: string
  locality?: string
  city?: string
  state?: string
  location_crs?: string
  confirmed_latitude?: number
  confirmed_longitude?: number
  confirmed_radius_m?: number
  confirmed_at?: string
  predicted_latitude?: number
  predicted_longitude?: number
  predicted_radius_m?: number
  predicted_at?: string
  place_cluster_id?: string
  latitude?: number
  longitude?: number
  confidence?: number
  confidence_radius_m?: number
  created_at: string
  remark_correction?: string
  coordinate_crs?: string
  updated_at: string
}

export interface NormalizedAddress {
  raw_address: string
  normalized_address: string
  language?: string
  entities: AddressEntity[]
  pincode?: string
  locality?: string
  city?: string
  state?: string
  landmark?: string
  confidence: number
}

export interface AddressEntity {
  entity_type: string
  value: string
  confidence: number
  relation?: string
  secondary_entity?: string
}

export interface Visit {
  visit_id: string
  account_id: string
  agent_id: string
  timestamp: string
  latitude: number
  longitude: number
  gps_accuracy?: number
  outcome: VisitOutcome
  dwell_time?: number
  remarks?: string
  trajectory: TrajectoryPoint[]
  integrity_score?: number
  reliability_score?: number
  created_at: string
}

export type VisitOutcome =
  | 'SUCCESSFUL_CONTACT'
  | 'PARTIAL_CONTACT'
  | 'FAILED_SEARCH'
  | 'ADDRESS_NOT_TRACEABLE'
  | 'WRONG_ADDRESS'
  | 'BORROWER_MOVED'
  | 'OTHER'

export interface TrajectoryPoint {
  latitude: number
  longitude: number
  timestamp: string
  accuracy?: number
  speed?: number
}

export interface CandidateLocation {
  candidate_id: string
  latitude: number
  longitude: number
  source: CandidateSource
  source_reference?: string
  address_similarity: number
  landmark_similarity: number
  locality_similarity: number
  distance_to_successful_visits?: number
  distance_to_failed_visits?: number
  supporting_visit_count: number
  weighted_successful_visit_count: number
  visit_integrity: number
  gps_accuracy?: number
  dwell_time?: number
  trajectory_quality: number
  nearby_account_support: number
  commercial_geocoder_distance?: number
  place_cluster_support: number
  agent_independence: number
  score?: number
  probability?: number
}

export type CandidateSource =
  | 'HISTORICAL_VISIT'
  | 'NEARBY_ACCOUNT'
  | 'GEOCODER'
  | 'LANDMARK'
  | 'LOCALITY'
  | 'PINCODE'
  | 'INTERPOLATION'

export interface PredictionEvidence {
  historical_visits: number
  reliable_visits: number
  nearby_accounts: number
  geocoder_support: boolean
  main_landmark?: string
  strongest_evidence: string[]
  visit_integrity_flags: string[]
  agent_bias_warnings: string[]
}

export interface Prediction {
  account_id: string
  latitude?: number
  longitude?: number
  confidence: number
  confidence_radius_m?: number
  prediction_method: string
  recommended_action: RecommendedAction
  directions: string
  evidence: PredictionEvidence
  model_version: string
  feature_version: string
  timestamp: string
  candidates?: CandidateLocation[]
}

export type RecommendedAction = 'VISIT_DIRECTLY' | 'VERIFY_FIRST' | 'LOW_CONFIDENCE'

export interface PlaceCluster {
  cluster_id: string
  latitude: number
  longitude: number
  account_ids: string[]
  landmarks: string[]
  address_variants: string[]
  visit_count: number
  confidence: number
  created_at: string
}

export interface Metrics {
  total_accounts: number
  total_visits: number
  predictions_made: number
  high_confidence_rate: number
  median_error_m?: number
  p90_error_m?: number
  confidence_coverage?: number
  calibration_error?: number
  address_not_traceable_rate: number
  productive_visits: number
  within_50m?: number
  within_100m?: number
  within_250m?: number
  within_500m?: number
  updated_at: string
}

export interface ModelInfo {
  model_name: string
  model_version: string
  feature_version: string
  embedding_model: string
  training_date?: string
  metrics: Record<string, number>
  ablation_results: Record<string, Record<string, number>>
}

export interface GeocodeRequest {
  account_id?: string
  address: string
  language?: string
  pincode?: string
  locality?: string
  city?: string
  state?: string
  use_cache?: boolean
}

export interface VisitCreateRequest {
  account_id: string
  agent_id: string
  timestamp: string
  latitude: number
  longitude: number
  gps_accuracy?: number
  outcome: VisitOutcome
  dwell_time?: number
  remarks?: string
  trajectory: TrajectoryPoint[]
}

// Real dataset types
export interface RealAccount {
  account_id: string
  town_id: string
  preferred_language: string
  portfolio: string
  income_type: string
}

export interface RealAddress {
  address_id: string
  account_id: string
  address_type: string
  address_text: string
  town_id: string
}

export interface RealFieldVisit {
  visit_id: string
  visit_date: string
  outcome: string
  checkin_x: number
  checkin_y: number
  gps_accuracy_m: number
  dwell_s: number
  remark?: string
}

export interface RealGeocodingResult {
  address_id: string
  account_id: string
  predicted_x: number | null
  predicted_y: number | null
  confidence: number
  confidence_radius_m: number | null
  recommended_action: string
  prediction_method: string
  evidence: {
    historical_visits: number
    reliable_visits: number
    nearby_accounts: number
    geocoder_support: boolean
    main_landmark?: string
    strongest_evidence: string[]
  }
  ground_truth_x?: number
  ground_truth_y?: number
  error_m?: number | null
}

export interface RealEvaluationResult {
  total_evaluated: number
  median_error_m: number
  mean_error_m: number
  p75_error_m?: number
  p90_error_m: number
  p95_error_m?: number
  within_50m: number
  within_100m: number
  within_250m: number
  within_500m: number
}