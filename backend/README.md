# Backend - AI-Native Field Address Geocoder

## Overview

FastAPI-based backend for the AI-Native Field Address Geocoder system. Provides REST APIs for geocoding, visit management, account management, and analytics.

## Architecture

```
backend/
├── app/              # FastAPI application
│   ├── main.py       # Application entry point
│   ├── schemas.py    # Pydantic models
│   └── routes/       # API route handlers
├── ml/               # ML modules
│   ├── address_normalizer.py
│   ├── entity_extractor.py
│   ├── visit_evidence.py
│   ├── visit_integrity.py
│   ├── place_resolution.py
│   ├── ranker.py
│   └── calibration.py
├── geospatial/       # Geospatial utilities
│   ├── candidate_generator.py
│   ├── directions.py
│   └── geocoder.py
├── data/             # Data access layer
│   ├── database.py
│   ├── models.py
│   └── repositories.py
├── evaluation/       # Evaluation pipeline
│   └── evaluate.py
├── tests/            # Unit/integration tests
├── scripts/          # Data generation, training
├── config/           # Configuration
├── requirements.txt
└── README.md
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/api/geocode` | Geocode single address |
| POST | `/api/geocode/batch` | Batch geocode |
| POST | `/api/visits` | Create visit record |
| POST | `/api/visits/validate` | Validate visit integrity |
| GET | `/api/visits/account/{id}` | Get visits by account |
| GET | `/api/visits/agent/{id}` | Get visits by agent |
| POST | `/api/accounts` | Create account |
| GET | `/api/accounts/{id}` | Get account |
| GET | `/api/accounts/{id}/evidence` | Get account evidence |
| GET | `/api/accounts/{id}/history` | Get prediction history |
| GET | `/api/accounts/{id}/prediction` | Get latest prediction |
| GET | `/api/place-clusters` | List place clusters |
| GET | `/api/metrics` | System metrics |
| GET | `/api/metrics/confidence-calibration` | Calibration data |
| GET | `/api/metrics/by-territory` | Territory metrics |
| GET | `/api/metrics/error-distribution` | Error distribution |
| GET | `/api/model/info` | Model information |
| GET | `/api/real/accounts` | List real dataset accounts |
| GET | `/api/real/accounts/{id}` | Get real account details |
| GET | `/api/real/addresses/{id}` | Get real address details |
| GET | `/api/real/addresses/{id}/geocode` | Geocode real address |
| GET | `/api/real/evaluate` | Evaluate on surveyed addresses |
| GET | `/api/real/evaluation/ps3` | Run and persist a versioned PS3 evaluation artifact |
| GET | `/api/real/towns` | List towns |
| GET | `/api/real/landmarks` | List landmarks |

## Setup

### Using Docker

```bash
docker compose up --build
```

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment variables
cp ../.env.example .env

# Train the LightGBM ranker model (optional but recommended)
python train_ranker.py

# Run server
python -m app.main
```

## Train LightGBM Ranker

```bash
# Train on real dataset (surveyed addresses as ground truth)
python train_ranker.py
```

This trains on all eligible surveyed addresses and creates
`models/ranker.txt`, which is automatically loaded in production.

## Evaluate on Real Dataset

```bash
# Evaluate geocoder on all surveyed addresses
python -m geospatial.real_geocoder

# Or via API
curl http://localhost:8000/api/real/evaluate
```

## Generate Demo Data (Synthetic)

```bash
python -m scripts.generate_demo_data
```

This creates synthetic accounts with clean, messy, and Hindi addresses plus realistic visit records.

## Run Tests

```bash
# All tests
pytest tests/ -v

# Specific test modules
pytest tests/test_api.py -v
pytest tests/test_coordinates.py -v
pytest tests/test_ranking.py -v
pytest tests/test_calibration.py -v
```

## Run Evaluation (Legacy)

```bash
python -m evaluation.evaluate
```

## Run Versioned PS3 Experiments

The PS3 runner persists a JSON artifact containing same-input baseline
comparisons, controlled ablations, radar metrics, geography holdouts, and
account-level temporal splits. Counterfactual IPW and doubly robust estimates
are emitted only when the input contains a treatment, numeric outcome, and
pre-treatment numeric covariates; otherwise the artifact explicitly reports
that the estimand is not identifiable.

```bash
python -m evaluation.ps3_experiments ..\Dataset --split train --output-dir ..\evaluation_artifacts
```

## ML Pipeline

1. **Normalization**: Unicode, abbreviations, punctuation
2. **Entity Extraction**: Landmarks, relations, directions, pincode
3. **Candidate Generation**: Historical visits, nearby accounts, geocoder
4. **Evidence Aggregation**: Reliability scoring, integrity detection
5. **Candidate Ranking**: LightGBM with 21 features
6. **Uncertainty Estimation**: Calibrated confidence + spatial radius

## Configuration

All configuration is in `config/settings.py` and can be overridden via environment variables.

Key settings:
- `CANDIDATE_COUNT`: Number of candidates to generate (default: 20)
- `CONFIDENCE_THRESHOLD_DIRECT`: Threshold for direct visit (default: 0.85)
- `CONFIDENCE_THRESHOLD_VERIFY`: Threshold for verification (default: 0.60)
- `DIRECT_VISIT_RADIUS_M`: Max radius for direct visit (default: 100m)

## Data Storage

Uses SQLite by default (configurable to PostgreSQL). Database file is created at `data/geocoder.db`.

## Model Artifacts

Trained models are saved to `models/`:
- `ranker.txt`: LightGBM ranking model
- `calibrator.joblib`: Confidence calibrator