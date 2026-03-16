# Green Odyssey — AI-Powered EV Road Trip Planner

Green Odyssey is an EV road trip planner that uses a Google ADK agent to create battery-aware itineraries with real charging stations, merged charge/rest stops, and precise trip timing.

## Architecture

```
Browser (Green Odyssey UI)
  ├── index.html        Landing page
  ├── planner.html      Trip planner form (city autocomplete, car picker, preferences)
  └── results.html      Results dashboard (timeline, Leaflet map, detail cards)
         │
         ▼  POST /api/plan-trip
FastAPI Server (server.py on Cloud Run)
         │
         ▼  agent_engine.stream_query()
Vertex AI Agent Engine
  ├── Google Search         (car specs lookup)
  ├── Google Maps REST API  (directions, place search, geocode)
  ├── calculate_battery_needs()
  └── plan_all_stops()
         │
         ▼  Structured JSON (TripPlan schema)
```

## What The Agent Does

1. Looks up EV battery specs via Google Search (battery capacity, consumption per km)
2. Gets driving route from Google Maps Directions API
3. Calculates battery feasibility and charge count
4. Builds a unified stop plan (charging + rest stops merged)
5. Finds real EV charging stations via Google Maps Places API
6. Returns structured JSON with a complete itinerary

## Repository Structure

```
├── server.py                    FastAPI backend (calls Agent Engine remotely)
├── deploy.py                    Deploy agent to Vertex AI Agent Engine + Model Armor
├── Dockerfile                   Cloud Run container (Python 3.12, no Node.js)
├── .dockerignore                Excludes agent code from Cloud Run image
├── requirements.txt             Python dependencies (dev + deploy)
├── README.md
├── ev_trip_planner/
│   ├── __init__.py
│   ├── agent.py                 ADK agent definition, tools, output schema (TripPlan)
│   └── maps_tools.py            Google Maps REST API tools (get_directions, search_places, geocode)
└── static/
    ├── index.html               Landing page
    ├── planner.html             Trip planner form
    ├── results.html             Results dashboard
    └── css/
        ├── style.css            Global styles
        ├── planner.css          Planner page styles
        └── results.css          Results page styles
```

## Deployment

### Agent Engine (Vertex AI)

The ADK agent is deployed to Agent Engine as a managed service. It uses Python function tools for Google Maps (no MCP/Node.js — Agent Engine only supports Python).

```bash
python deploy.py
# Outputs: projects/.../reasoningEngines/XXXXXX
```

### Cloud Run (Web App)

The FastAPI server + static UI is containerized and deployed to Cloud Run. It calls Agent Engine remotely via the Vertex AI SDK.

```bash
# Build and push
docker build --platform linux/amd64 -t us-central1-docker.pkg.dev/<PROJECT>/ev-trip-planner/app:latest .
docker push us-central1-docker.pkg.dev/<PROJECT>/ev-trip-planner/app:latest
```

Deploy via App Design Center or `gcloud run deploy` with these env vars:

| Variable | Value |
|----------|-------|
| `GOOGLE_CLOUD_PROJECT` | Your GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` |
| `AGENT_ENGINE_RESOURCE_NAME` | Resource name from `deploy.py` output |

### Local Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python server.py
# http://localhost:8000
```

For local development, `server.py` calls Agent Engine remotely (same as production). Set the `AGENT_ENGINE_RESOURCE_NAME` env var or update the default in `server.py`.

## Environment Variables

| Where | Variable | Purpose |
|-------|----------|---------|
| Agent Engine | `GOOGLE_GENAI_USE_VERTEXAI` | Use Vertex AI for Gemini |
| Agent Engine | `GOOGLE_MAPS_API_KEY` | Google Maps API access |
| Cloud Run | `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| Cloud Run | `GOOGLE_CLOUD_LOCATION` | GCP region |
| Cloud Run | `AGENT_ENGINE_RESOURCE_NAME` | Agent Engine resource path |

## Tech Stack

- **Agent**: Google ADK, Gemini 2.5 Flash, Pydantic output schema
- **Backend**: FastAPI, Vertex AI SDK
- **Frontend**: Vanilla HTML/CSS/JS, Leaflet maps, Lucide icons
- **Infrastructure**: Vertex AI Agent Engine, Cloud Run, Artifact Registry, Model Armor
