# Frontend - AI-Native Field Address Geocoder

## Overview

React + TypeScript frontend for the AI-Native Field Address Geocoder system. Provides dashboard, account search, address intelligence, map view, field agent view, analytics, and model benchmark pages.

## Tech Stack

- **React 18** with TypeScript
- **Vite** for build tooling
- **Tailwind CSS** for styling
- **Leaflet** for maps
- **Recharts** for analytics
- **React Router** for navigation
- **Axios** for API calls

## Pages

| Page | Route | Description |
|------|-------|-------------|
| Dashboard | `/` | System overview and key metrics |
| Account Search | `/search` | Search accounts by address, locality, pincode |
| Address Intelligence | `/address/:id` | Detailed address analysis and prediction |
| Map View | `/map/:id` | Geographic visualization with confidence circles |
| Field Agent View | `/field/:id` | Mobile-friendly view for field agents |
| Analytics | `/analytics` | Error distribution, calibration, territory performance |
| Model Benchmark | `/benchmark` | Baseline comparison and ablation study |

## Setup

### Using Docker

```bash
docker compose up --build
```

### Local Development

```bash
# Install dependencies
npm install

# Start dev server
npm run dev
```

The dev server runs on http://localhost:3000 and proxies API requests to http://localhost:8000.

## Build

```bash
# Production build
npm run build

# Preview production build locally
npm run preview
```

## Type Checking

```bash
# Run TypeScript compiler check
npm run type-check
```

## Linting

```bash
# Run ESLint
npm run lint
```

## Environment Variables

Create a `.env` file in the frontend directory:

```env
VITE_API_URL=http://localhost:8000
```

## Project Structure

```
frontend/
├── src/
│   ├── components/     # Reusable components
│   ├── pages/          # Page components
│   ├── services/       # API services
│   ├── hooks/          # Custom hooks
│   ├── utils/          # Utilities
│   ├── types/          # TypeScript types
│   ├── assets/         # Static assets
│   ├── App.tsx         # Main app component
│   ├── main.tsx        # Entry point
│   └── index.css       # Global styles
├── public/             # Public assets
├── package.json
├── vite.config.ts
├── tailwind.config.js
└── tsconfig.json
```