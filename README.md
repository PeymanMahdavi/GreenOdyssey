# GreenOdyssey - EV Trip Planner Agent

GreenOdyssey is a Python-based EV road trip planning agent built with Google ADK and deployed to Vertex AI Agent Engine.

The agent creates battery-aware itineraries with real charging stations (name + address), merged charge/rest stops, and total trip timing.

## Project Definition

- Project name: `GreenOdyssey`
- Type: Google ADK agent application
- Primary goal: Plan practical EV trips using real route and charging data
- Deployment target: Vertex AI Agent Engine (`us-central1` in current code)

## What The Agent Does

1. Collects trip inputs:
- Start and destination
- Car model
- Average speed and preferred break interval

2. Looks up EV specs (if user does not provide them):
- Battery capacity (kWh)
- Consumption (kWh/km)

3. Gets route details from Google Maps MCP tools:
- Total distance and duration
- Route steps and major cities/towns

4. Calculates battery feasibility and charge count using:
- `calculate_battery_needs(...)`

5. Builds a unified stop plan using:
- `plan_all_stops(...)`
- Merges rest and charging when nearby

6. Resolves charging stops to real stations:
- Station name
- Full address
- Nearby city

7. Returns a detailed itinerary:
- Stop-by-stop table
- Battery estimates
- Total drive/stop/trip time

## Repository Structure

- `deploy.py`: Deploy script for Vertex AI Agent Engine and Model Armor template creation
- `ev_trip_planner/agent.py`: Agent instructions, tool configuration, and planning functions
- `ev_trip_planner/__init__.py`: Package init
- `requirements.txt`: Python dependencies

## Dependencies

From `requirements.txt`:

- `google-adk`
- `google-cloud-aiplatform[adk,agent_engines]`
- `mcp`

Also used in `deploy.py`:

- `google-cloud-modelarmor` (for `google.cloud.modelarmor_v1`)

## Environment And Configuration

Current constants in `deploy.py`:

- `PROJECT_ID = "qwiklabs-asl-02-c74cc833bee1"`
- `LOCATION = "us-central1"`
- `STAGING_BUCKET = f"gs://{PROJECT_ID}-staging"`

Required environment variable for maps tooling:

- `GOOGLE_MAPS_API_KEY`

Model Armor config currently includes:

- Template ID: `green-odyssey-safety`
- Parent: `projects/YOUR_PROJECT/locations/us-central1` (replace `YOUR_PROJECT`)

## Quick Start

1. Create and activate a Python virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
pip install google-cloud-modelarmor
```

3. Set required environment variables (at minimum `GOOGLE_MAPS_API_KEY`).
4. Update `deploy.py` values:
- `PROJECT_ID`
- Model Armor `parent`
- Any other project/location settings as needed

5. Deploy:

```bash
python deploy.py
```

## Notes

- The agent model is currently set to `gemini-2.5-flash-lite`.
- The deploy script currently runs Model Armor template creation at import/runtime before agent deployment.
- No test suite is currently present in this repository snapshot.
