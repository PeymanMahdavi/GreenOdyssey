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
├── deploy.py                    Deploy agent to Vertex AI Agent Engine
├── Dockerfile                   Cloud Run container (Python 3.12)
├── .dockerignore                Excludes agent code from Cloud Run image
├── requirements.txt             Python dependencies (dev + deploy)
├── README.md
├── ev_trip_planner/
│   ├── __init__.py
│   ├── agent.py                 ADK agent definition, tools, output schema (TripPlan)
│   └── maps_tools.py            Google Maps REST API tools (condensed responses)
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

### 1. Deploy the Agent (Vertex AI Agent Engine)

The ADK agent is deployed to Agent Engine as a managed service. It uses Python function tools for Google Maps (Agent Engine only supports Python).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python deploy.py
# Outputs: projects/<PROJECT_NUMBER>/locations/us-central1/reasoningEngines/<ID>
```

Copy the resource name and update the default in `server.py` (`AGENT_ENGINE_RESOURCE_NAME`).

### 2. Build and Push the Docker Image

```bash
docker build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/<PROJECT_ID>/ev-trip-planner/green-odyssey:latest .
docker push us-central1-docker.pkg.dev/<PROJECT_ID>/ev-trip-planner/green-odyssey:latest
```

### 3. Deploy to Cloud Run

```bash
gcloud run deploy <SERVICE_NAME> \
  --image us-central1-docker.pkg.dev/<PROJECT_ID>/ev-trip-planner/green-odyssey:latest \
  --region us-central1
```

### Required IAM Roles for the Cloud Run Service Account

The Cloud Run service account needs these roles (App Design Center does not grant them automatically):

| Role | Purpose |
|------|---------|
| `roles/artifactregistry.reader` | Pull the container image from Artifact Registry |
| `roles/aiplatform.user` | Call the Vertex AI Agent Engine |

```bash
SA="<SERVICE_ACCOUNT>@<PROJECT_ID>.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding <PROJECT_ID> --member="serviceAccount:$SA" --role="roles/artifactregistry.reader"
gcloud projects add-iam-policy-binding <PROJECT_ID> --member="serviceAccount:$SA" --role="roles/aiplatform.user"
```

### VPC Egress Configuration

If deploying via App Design Center, the Cloud Run service may default to `vpc-access-egress: all-traffic`, which routes all outbound traffic through the VPC. If the VPC lacks a Cloud NAT gateway, the container cannot reach external APIs (Vertex AI, Google Maps). Fix by setting egress to `private-ranges-only`:

```bash
gcloud run services update <SERVICE_NAME> --region=us-central1 --vpc-egress=private-ranges-only
```

### Local Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python server.py
# http://localhost:8000
```

The local server calls Agent Engine remotely (same as production). Set `AGENT_ENGINE_RESOURCE_NAME` as an env var or update the default in `server.py`.

To proxy a deployed Cloud Run service locally (with auth):

```bash
gcloud run services proxy <SERVICE_NAME> --region=us-central1 --port=8080
# http://127.0.0.1:8080
```

## Environment Variables

| Where | Variable | Purpose |
|-------|----------|---------|
| Agent Engine | `GOOGLE_GENAI_USE_VERTEXAI` | Use Vertex AI for Gemini |
| Agent Engine | `GOOGLE_MAPS_API_KEY` | Google Maps API access |
| Cloud Run | `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| Cloud Run | `GOOGLE_CLOUD_LOCATION` | GCP region |
| Cloud Run | `AGENT_ENGINE_RESOURCE_NAME` | Agent Engine resource path |

## Model Armor (Content Safety)

Model Armor screens all Gemini API calls for prompt injection, jailbreak attempts, malicious URIs, and harmful content. It is integrated at the Vertex AI level via **floor settings**, meaning all `generateContent` calls in the project are automatically protected.

### What's configured

| Filter | Enforcement |
|--------|-------------|
| Prompt injection / jailbreak | Enabled, LOW_AND_ABOVE confidence |
| Malicious URI detection | Enabled |
| Hate speech | MEDIUM_AND_ABOVE |
| Dangerous content | MEDIUM_AND_ABOVE |
| Sexually explicit | MEDIUM_AND_ABOVE |
| Harassment | MEDIUM_AND_ABOVE |

Mode: `INSPECT_ONLY` with Cloud Logging enabled (logs violations without blocking). Change to `INSPECT_AND_BLOCK` for production use.

### Setup commands

```bash
# 1. Enable the API
gcloud services enable modelarmor.googleapis.com

# 2. Grant Model Armor user to Vertex AI service account
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:service-<PROJECT_NUMBER>@gcp-sa-aiplatform.iam.gserviceaccount.com" \
  --role="roles/modelarmor.user"

# 3. Create the template (also done by deploy.py)
python -c "from deploy import create_armor_template; create_armor_template()"

# 4. Enable floor settings with Vertex AI integration
curl -X PATCH \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -d '{
    "filterConfig": {
      "raiSettings": {
        "raiFilters": [
          {"filterType": "HATE_SPEECH", "confidenceLevel": "MEDIUM_AND_ABOVE"},
          {"filterType": "DANGEROUS", "confidenceLevel": "MEDIUM_AND_ABOVE"},
          {"filterType": "SEXUALLY_EXPLICIT", "confidenceLevel": "MEDIUM_AND_ABOVE"},
          {"filterType": "HARASSMENT", "confidenceLevel": "MEDIUM_AND_ABOVE"}
        ]
      },
      "piAndJailbreakFilterSettings": {"filterEnforcement": "ENABLED", "confidenceLevel": "LOW_AND_ABOVE"},
      "maliciousUriFilterSettings": {"filterEnforcement": "ENABLED"}
    },
    "integratedServices": ["AI_PLATFORM"],
    "aiPlatformFloorSetting": {"inspectOnly": true, "enableCloudLogging": true},
    "enableFloorSettingEnforcement": true
  }' \
  "https://modelarmor.googleapis.com/v1/projects/<PROJECT_ID>/locations/global/floorSetting"

# 5. (Optional) Switch to blocking mode for production
gcloud model-armor floorsettings update \
  --full-uri=projects/<PROJECT_ID>/locations/global/floorSetting \
  --vertex-ai-enforcement-type=INSPECT_AND_BLOCK
```

## Key Implementation Notes

- **Maps tool responses are condensed**: `get_directions`, `search_places`, and `geocode` strip polylines, HTML instructions, and bulk metadata from Google Maps API responses. The Vertex AI SDK has a size limit on function responses (~64KB), and raw Directions API responses for long routes can exceed 100KB.
- **Stream events are dicts**: `agent_engine.stream_query()` returns events as Python dicts, not protobuf objects. Access fields with `event.get("content")` rather than `event.content`.
- **Markdown fence stripping**: The agent may wrap its JSON output in `` ```json `` fences. The server strips these before parsing.
- **Redeploying the agent**: After changing tools in `ev_trip_planner/`, you must run `python deploy.py` to create a new Agent Engine, then update `AGENT_ENGINE_RESOURCE_NAME` in `server.py` and redeploy the Cloud Run image.

## Tech Stack

- **Agent**: Google ADK, Gemini 2.5 Flash, Pydantic output schema
- **Backend**: FastAPI, Vertex AI SDK
- **Frontend**: Vanilla HTML/CSS/JS, Leaflet maps, Lucide icons
- **Safety**: Model Armor (prompt injection, RAI filters, malicious URI detection)
- **Infrastructure**: Vertex AI Agent Engine, Cloud Run, Artifact Registry
