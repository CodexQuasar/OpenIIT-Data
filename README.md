# AI-Native Field Address Geocoder

> **Implementation status:** functional PS3 prototype with authenticated operational APIs, continuous visit-evidence learning, confirmed/predicted location separation, offline visit synchronization, planner/RPC integration surfaces, and measured evaluation endpoints. Production rollout still requires lender-specific tenant isolation, retention policies, controlled pilot design, and route optimization integration.

## Project Overview

Geocoding system for Indian debt-collection field operations that learns from field visits. Takes messy Indian borrower addresses, historical field-visit GPS evidence, visit outcomes, GPS trails, dwell time, agent remarks, and nearby confirmed accounts to produce accurate location predictions with calibrated uncertainty.

## Key Problem

Indian debt-collection field operations struggle with messy, non-standardized borrower addresses. Agents waste time searching for locations, and existing geocoders fail on landmark-based, multilingual, and abbreviated Indian addresses.

## Solution

The system learns from historical field-visit GPS evidence, explicitly models evidence reliability (not every GPS point is ground truth), and continuously improves as trustworthy field visits are added.

## Core Differentiator

> **Every reliable field visit improves the geocoder.**

This learning loop is the central product and ML story.

## Account Search and Administration

The **Account Search** page queries the real dataset endpoint with an optional
server-side `search` term. Searches match account ID, town, preferred language,
and address text, then return the same paginated account records used by the
address-intelligence workflow. This avoids limiting users to the first 100
accounts loaded in the browser.

The **Admin** page is shown only to users whose authenticated role is `admin`.
It displays the deployed model metadata and provides a protected
`POST /api/model/retrain` action that queues retraining. Model metadata remains
readable through `GET /api/model/info` for existing operational health checks;
the retraining action is the privileged operation. A production deployment
should extend this panel with tenant policy, audit, retention, user-management,
and deployment controls rather than exposing those controls to field agents.

## Architecture
```
Frontend (React + TypeScript)
  Dashboard | Account Search | Address Intelligence | Maps | Benchmark | Admin (admin role)
                              |
                              v REST API
Backend (FastAPI)
  /api/geocode | /api/visits | /api/accounts | /api/planner | /api/rpc
  /api/metrics | /api/model/info | /api/model/retrain | /health
      |                         |
      v                         v
ML modules                 Geospatial modules
- Address normalization   - Candidate generation
- Entity extraction       - Evidence aggregation
- Visit integrity         - Candidate ranking
- Place resolution        - Uncertainty and calibration
```

## ML Pipeline

```
Raw address
  |
  v
Normalization (Unicode, transliteration, abbreviations, typos)
  |
  v
Entity extraction (landmarks, relations, directions, pincode)
  |
  v
Candidate generation
  - historical successful visits
  - nearby confirmed accounts
  - shared address/place clusters
  - commercial/open geocoder
  - known landmarks and locality centroids
  |
  v
Evidence aggregation
  - GPS accuracy, dwell, trajectory, and outcome
  - visit integrity and agent-influence controls
  - place-cluster support
  |
  v
Candidate ranking (LightGBM, 21 features)
  |
  v
Best candidate plus uncertainty, action, directions, and evidence
```

## Data Leakage Prevention

**Critical**: Time-aware evaluation only.

- Training: past visits only
- Evaluation: later visits only
- Account-level splits
- Geography-based splits
- No random splitting of visit records

## Real Dataset Evaluation (from Dataset folder)

Evaluation is served by `/api/real/evaluate` and uses the surveyed addresses in
`Dataset/PS_3`. The evaluation path explicitly handles the dataset's projected
local `x/y` coordinates rather than treating them as WGS84 latitude/longitude.
It reports model error percentiles and a measured commercial-geocoder baseline.
The current dataset contains 66 surveyed addresses, 3,896 visits, and 240
landmarks. Run the endpoint or the real-data evaluation command to obtain
current values; benchmark numbers are not hard-coded in the UI.

## Quick Start

### Using Docker

```bash
docker compose up --build
```

### Local Development

```bash
# Backend (PowerShell on Windows)
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item ..\.env.example .env

# Train the LightGBM ranker model (optional but recommended)
python train_ranker.py

# Start backend server
python -m app.main

# Frontend
cd frontend
npm install
npm run dev  # Runs on http://localhost:3000
```

Operational APIs require a JWT outside test mode. Create an account or sign in
through the frontend, or use the authentication endpoints before calling
account, visit, geocode, planner, real-data, or metrics routes:

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"operator@example.com","password":"change-this-password","full_name":"Operator"}'

curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"operator@example.com","password":"change-this-password"}'
```

The frontend stores the token locally, attaches it to API calls, handles expiry,
and signs the user out after an unauthorized response. Use the bearer token
returned by login for authenticated requests.

### PowerShell API testing

In Windows PowerShell, `curl` is an alias for `Invoke-WebRequest`, so flags
such as `-X`, `-H`, and `-d` do not behave like Unix `curl`. Use `curl.exe`
explicitly. Operational endpoints also require a JWT outside test mode:

```powershell
$base = "http://localhost:8000"

# Register a first user. The first registered user becomes an admin.
curl.exe -X POST "$base/api/auth/register" `
  -H "Content-Type: application/json" `
  --data-raw '{"username":"operator","password":"change-this-password","full_name":"Operator","tenant_id":"demo"}'

# Login and save the bearer token.
$login = curl.exe -sS -X POST "$base/api/auth/login" `
  -H "Content-Type: application/json" `
  --data-raw '{"username":"operator","password":"change-this-password"}' |
  ConvertFrom-Json
$token = $login.access_token
$headers = @{ Authorization = "Bearer $token" }

# Authenticated example.
Invoke-RestMethod -Method Post -Uri "$base/api/geocode" `
  -Headers $headers -ContentType "application/json" `
  -Body '{"address":"Hanuman mandir ke piche ration shop ke pas 2nd gali","language":"hi"}'

# Health does not require authentication.
Invoke-RestMethod -Method Get -Uri "$base/health"
```

If the server is not running, start it in another PowerShell window:

```powershell
Set-Location .\backend
.\venv\Scripts\python.exe -m app.main
```

Expected unauthenticated behaviour is `401 Unauthorized`, not a backend
failure. A `Failed to connect` or `Connection refused` error means the
FastAPI server is not running at `localhost:8000`. A `404` usually means the
URL is missing the `/api` prefix or uses the wrong route.

### Backend Commands

```bash
# Run all backend tests
python -m pytest tests/ -v

# Run specific test module
python -m pytest tests/test_api.py -v

# Train LightGBM candidate ranker
python train_ranker.py

# Evaluate on real dataset (surveyed addresses)
python -m geospatial.real_geocoder

# Load and explore real dataset
python -c "
from data.real_data import RealDatasetLoader
loader = RealDatasetLoader()
loader.load_all('train')
print(f'Accounts: {len(loader.accounts)}')
print(f'Addresses: {len(loader.addresses)}')
print(f'Visits: {len(loader.field_visits)}')
print(f'Surveyed: {len(loader.surveyed_addresses)}')
"
```

### API Usage

```bash
# Geocode a single address
curl -X POST http://localhost:8000/api/geocode \
  -H "Content-Type: application/json" \
  -d '{"address": "Hanuman mandir ke piche ration shop ke pas 2nd gali", "language": "hi"}'

# Batch geocode multiple addresses
curl -X POST http://localhost:8000/api/geocode/batch \
  -H "Content-Type: application/json" \
  -d '{"accounts": [{"account_id": "ACC001", "address": "123 Main St, Bangalore"}, {"account_id": "ACC002", "address": "456 Cross Rd, Mumbai"}]}'

# Create a visit (triggers prediction refresh and account location write-back)
curl -X POST http://localhost:8000/api/visits \
  -H "Content-Type: application/json" \
  -d '{"account_id": "ACC001", "agent_id": "AGENT001", "timestamp": "2024-01-01T10:00:00", "latitude": 12.9716, "longitude": 77.5946, "gps_accuracy": 10.0, "outcome": "SUCCESSFUL_CONTACT", "dwell_time": 300, "remarks": "Met borrower"}'

# Validate visit integrity (without saving)
curl -X POST http://localhost:8000/api/visits/validate \
  -H "Content-Type: application/json" \
  -d '{"visit": {"account_id": "ACC001", "agent_id": "AGENT001", "timestamp": "2024-01-01T10:00:00", "latitude": 12.9716, "longitude": 77.5946, "gps_accuracy": 10.0, "outcome": "SUCCESSFUL_CONTACT", "dwell_time": 300}, "check_historical": true}'

# Get visits for an account
curl http://localhost:8000/api/visits/account/ACC001

# Get all accounts
curl http://localhost:8000/api/accounts

# Search accounts
curl "http://localhost:8000/api/accounts?search=Bangalore"

# Get latest prediction for an account
curl http://localhost:8000/api/accounts/ACC001/prediction

# Get prediction history
curl http://localhost:8000/api/accounts/ACC001/history

# Get account evidence
curl http://localhost:8000/api/accounts/ACC001/evidence

# Get system metrics (includes real evaluation data)
curl http://localhost:8000/api/metrics

# Get confidence calibration data
curl http://localhost:8000/api/metrics/confidence-calibration

# Get territory metrics
curl http://localhost:8000/api/metrics/by-territory

# Get error distribution
curl http://localhost:8000/api/metrics/error-distribution

# Get productivity and address-not-traceable metrics
curl http://localhost:8000/api/metrics/productivity

# Get explainable visit priorities
curl "http://localhost:8000/api/planner/visits?limit=100"

# Get PS2/right-party-contact location features for an account
curl http://localhost:8000/api/rpc/location-features/ACC001

# Get model info
curl http://localhost:8000/api/model/info

# Health check
curl http://localhost:8000/health
```

### Real Dataset API (loads from Dataset/ folder)

```bash
# List accounts from real dataset
curl "http://localhost:8000/api/real/accounts?limit=10"

# Get account details with addresses and visits
curl http://localhost:8000/api/real/accounts/ACC123

# Get address with visits, baseline geocode, and surveyed ground truth
curl http://localhost:8000/api/real/addresses/ADDR123

# Geocode a real address using production pipeline
curl http://localhost:8000/api/real/addresses/ADDR123/geocode

# Evaluate geocoder on all surveyed addresses
curl http://localhost:8000/api/real/evaluate

# List towns
curl http://localhost:8000/api/real/towns

# List landmarks (optionally filter by town)
curl "http://localhost:8000/api/real/landmarks?town_id=TOWN001"
```

## Reproducible PS3 evaluation artifacts

The PS3 evaluation runner creates versioned, hash-addressed JSON artifacts
using projected local coordinates in metres:

```powershell
cd backend
.\venv\Scripts\python.exe -m evaluation.ps3_experiments ..\Dataset `
  --split train --output-dir ..\evaluation_artifacts
```

Each `ps3_eval_<run_id>.json` artifact records the artifact version, UTC run
ID, configuration, SHA-256 hashes of the input CSVs, dataset counts, metrics
and explicit evidence boundaries. It compares:

- commercial geocoder;
- nearest reliable visit;
- weighted visit centroid;
- address-only, address-plus-visits and integrity-weighted ablations;
- a leakage-safe temporal diagnostic using pre-cutoff visits;
- an unseen-town address-only geography holdout;
- accuracy, coverage, calibration, robustness, explainability and latency
  radar inputs.

Metrics use Euclidean distance over the PS3 projected `x/y` coordinate system.
The geography result is a baseline diagnostic; production-model retraining on
train towns is required before claiming generalization. Nearby-account
ablation is marked `not_estimable` when the dataset has no independent
nearby-evidence table. Counterfactual IPW/doubly robust evaluation is also
explicitly marked `not_estimable` until treatment assignment, recovery outcome
and pre-treatment covariates are collected. The runner never fabricates a
causal estimate from visit outcomes alone.

The generated artifact is consumed by the final section of
`Submission/PS3_Geocoder_EDA.ipynb`. A detailed problem, architecture,
evaluation and deployment explanation is available in
`PS3_PROBLEM_SOLUTION_REPORT.md`.

## Test Results

The current backend suite has 92 passing tests, covering:

- Address normalization (12 tests)
- Coordinate calculations (12 tests)
- Candidate ranking (5 tests)
- Confidence calibration (6 tests)
- Reproducible PS3 evaluation artifacts (3 tests)
- API, authentication, compliance, and visit flows
- Real dataset evaluation and projected-coordinate handling
- Evidence reliability, place resolution, and persistence

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test categories
python -m pytest tests/test_api.py -v
python -m pytest tests/test_coordinates.py -v
python -m pytest tests/test_ranking.py -v
python -m pytest tests/test_calibration.py -v
```

Frontend validation:

```bash
cd frontend
npm run lint
npm run build
```

Both commands currently pass.

### UI theme and Google Maps

The frontend includes a persistent light/dark mode toggle in the navigation
bar. The preference is stored in `localStorage` under `theme`.

Google Maps is optional and must be configured with a browser-restricted key:

```bash
# frontend/.env.local
VITE_GOOGLE_MAPS_API_KEY=your-restricted-browser-key
```

Enable the Google Maps JavaScript API and billing in Google Cloud, then
restrict the key by HTTP referrer and API scope. The UI only sends WGS84
latitude/longitude to Google Maps. PS3 evaluation `x/y` coordinates remain in
the local-coordinate scatter plot and are never treated as Google coordinates.

## Frontend Build

```bash
cd frontend
npm run build  # Production build
npm run dev    # Development server
```

## Project Structure

```
project-root/
  backend/       FastAPI app, ML, geospatial, data, tests, configuration
  frontend/      React/TypeScript application and service worker
  Dataset/       Shared data and PS_3 evaluation data
  models/        Trained model artifacts
  docker-compose.yml
  .env.example
  README.md
```

## Configuration

All configuration via `config/settings.py` and environment variables. Key settings:

- `CANDIDATE_COUNT`: Number of candidates (default: 20)
- `CONFIDENCE_THRESHOLD_DIRECT`: 0.85 (for VISIT_DIRECTLY)
- `CONFIDENCE_THRESHOLD_VERIFY`: 0.60 (for VERIFY_FIRST)
- `DIRECT_VISIT_RADIUS_M`: 100m
- `VERIFICATION_RADIUS_M`: 500m
- `EMBEDDING_MODEL`: sentence-transformers model

### Location evidence model

Account location records distinguish the current operational location from
the evidence used to produce it:

- `confirmed_latitude`, `confirmed_longitude`, `confirmed_radius_m`,
  `confirmed_at`: high-quality confirmed visit location.
- `predicted_latitude`, `predicted_longitude`, `predicted_radius_m`,
  `predicted_at`: latest model prediction.
- `latitude`, `longitude`, `confidence`, `confidence_radius_m`,
  `location_source`, `location_crs`: canonical location used by operational
  consumers.

Confirmed visit evidence cannot be overwritten by a weaker prediction.
`coordinate_crs` is persisted on visits and `location_crs` on accounts so
projected evaluation coordinates are not silently interpreted as WGS84.
Startup calls `create_all()` and applies additive SQLite column upgrades for
these nullable fields; use a managed migration process before production
deployment.

## ML Training Pipeline

The system includes a LightGBM candidate ranker that can be trained on the real dataset:

```bash
# Train the ranker (uses surveyed addresses as ground truth)
python train_ranker.py
```

Training process:
1. Loads real dataset (accounts, visits, surveyed addresses)
2. Creates candidates from historical successful visits + baseline geocodes
3. Labels candidates: 1 if within 250m of surveyed location, 0 otherwise
4. Trains LightGBM binary classifier with early stopping
5. Saves the full-data model to `models/ranker.txt`

The trained model is automatically loaded by `CandidateRanker` in production.
Training uses all eligible surveyed addresses; the account-level holdout is
kept separate to avoid evaluation leakage.

## Continuous Improvement Loop

The system implements the core learning loop: **every reliable field visit improves the geocoder**.

```
Field visit created
        |
        v
Reliability + integrity scoring
(GPS accuracy, dwell, trajectory, outcome)
        |
        v
Background prediction refresh
(re-rank candidates with new evidence)
        |
        v
Confirmed visit -> confirmed location fields
Prediction      -> predicted location fields
        |
        v
Cluster evidence enrichment when thresholds pass
```

This loop runs automatically on every `POST /api/visits` request via background tasks.

Visit remarks are retained as an auditable `remark_correction` phrase when a
correction pattern is detected. Visit integrity and reliability scores are used
to reduce the influence of low-quality or potentially fake visits. Cluster
propagation is guarded by source/reliability checks; it is not a substitute
for lender-specific place verification.

## Planner and PS2 integration

`GET /api/planner/visits` exposes a minimal explainable planner contract with
coordinates, confidence, radius, source, and a recommended action:

- `verify_first` for low-confidence locations;
- `visit_directly` for confirmed or sufficiently confident locations;
- `skip_until_geocoded` when no usable coordinates exist.

Optional `origin_latitude`, `origin_longitude`, and `max_distance_km` query
parameters add deterministic distance-aware prioritization and a distance
budget. This is still a prioritizer, not a road-network route optimizer.

`GET /api/rpc/location-features/{account_id}` exposes location features for a
right-party-contact/address-health model: confidence, radius, source,
successful visits, failed searches, and whether the location is confirmed.
These are integration surfaces, not a complete RPC model or production route
optimizer.

## Offline operation

The frontend queues visit submissions in IndexedDB when connectivity is
unavailable. The service worker caches static assets, GET responses, and map
tiles. Queued requests include the current bearer token when synchronized.
Failed submissions are retried up to five times and then moved to a local
dead-letter store with the HTTP/network error and failure timestamp. Conflict
resolution and complete offline caching of planner/account/directions data
remain deployment work.

## Compliance and operational boundaries

- Operational routes require JWT authentication outside `TESTING=1`.
- RBAC and permission dependencies are available for account, visit, metrics,
  audit, consent, and system operations.
- Location evidence is intended for collections operations only.
- RBI contact-hour/frequency rules, DPDP consent/retention enforcement, and
  tenant-specific data filtering must be configured and audited for each
  deployment; this repository does not claim that a generic prototype
  configuration satisfies every lender's legal obligations.
- Agent GPS integrity signals are used for evidence quality and must be
  governed under the applicable employment and monitoring framework.
- RBAC is relevant because borrower locations, visit trails, agent evidence,
  planner output, and operational metrics are sensitive. Lender users,
  field agents, auditors, and administrators should receive only the
  account, visit, export, configuration, and audit permissions required for
  their role. The backend already exposes permission dependencies; deployment
  must apply tenant/territory scoping to those permissions.

## Known limitations

- The planner supports deterministic distance-aware prioritization when an
  origin and distance budget are supplied; it does not yet perform full
  road-network travel-time routing or cost-aware channel optimization.
- Controlled incumbent-policy comparisons and productive-visits-per-agent-day
  pilots require operational treatment/control data. The productivity endpoint
  reports descriptive database metrics only.
- Remark correction extraction is intentionally conservative phrase capture; it
  does not yet normalize every multilingual relation into a geometric offset.
- Cluster enrichment and propagation are guarded but require lender-scale
  thresholds and monitoring before enabling broad write-back.
- Ranker training now uses a deterministic account-level 80/20 partition and
  asserts zero account overlap before fitting.
