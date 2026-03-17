import os
import json
import logging
import re
import requests

import vertexai
from google.cloud import modelarmor_v1
from google.api_core import exceptions as google_exceptions
from google.api_core.client_options import ClientOptions
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-asl-02-c74cc833bee1")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
AGENT_ENGINE_RESOURCE_NAME = os.environ.get(
    "AGENT_ENGINE_RESOURCE_NAME",
    "projects/1050509607684/locations/us-central1/reasoningEngines/1769878369672888320",
)

MODEL_ARMOR_TEMPLATE = f"projects/{PROJECT_ID}/locations/{LOCATION}/templates/green-odyssey-safety"

client = vertexai.Client(project=PROJECT_ID, location=LOCATION)
agent_engine = None

ma_client = modelarmor_v1.ModelArmorClient(
    transport="rest",
    client_options=ClientOptions(
        api_endpoint=f"modelarmor.{LOCATION}.rep.googleapis.com"
    ),
)


def check_model_armor_template():
    """Verify that the Model Armor template exists on startup."""
    try:
        logger.info(f"Checking for Model Armor template: {MODEL_ARMOR_TEMPLATE}")
        ma_client.get_template(name=MODEL_ARMOR_TEMPLATE)
        logger.info("Model Armor template found successfully.")
    except google_exceptions.NotFound:
        logger.critical(
            f"Model Armor template '{MODEL_ARMOR_TEMPLATE}' not found. "
            "The application will not be able to process requests safely. "
            "Please run the deploy.py script to create the template."
        )
        raise RuntimeError(f"Model Armor template not found: {MODEL_ARMOR_TEMPLATE}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while checking for Model Armor template: {e}")
        raise


def get_agent_engine():
    global agent_engine
    if agent_engine is None:
        if not AGENT_ENGINE_RESOURCE_NAME:
            raise RuntimeError("AGENT_ENGINE_RESOURCE_NAME env var is not set")
        agent_engine = client.agent_engines.get(name=AGENT_ENGINE_RESOURCE_NAME)
    return agent_engine


app = FastAPI()


@app.on_event("startup")
async def startup_event():
    get_agent_engine()
    check_model_armor_template()


class PlanTripRequest(BaseModel):
    start_city: str
    dest_city: str
    car_brand: str
    car_model: str
    travel_style: str = "balanced"
    trip_mood: str = "relaxed"
    speed_kmh: float = 100.0
    max_drive_hours: float = 2.0
    custom_prompt: str = ""


@app.post("/api/plan-trip")
async def plan_trip(request: PlanTripRequest):
    car_full = f"{request.car_brand} {request.car_model}".strip()

    prompt = (
        f"Plan an EV road trip from {request.start_city} to {request.dest_city}. "
        f"Car: {car_full}. "
        f"Average speed: {request.speed_kmh} km/h. "
        f"Max driving before a break: {request.max_drive_hours} hours. "
        f"Travel style: {request.travel_style}. "
        f"Trip mood: {request.trip_mood}. "
    )

    if request.custom_prompt:
        prompt += f" Additional preferences: {request.custom_prompt}"

    # --- Model Armor Safety Check ---
    try:
        ma_request = modelarmor_v1.SanitizeUserPromptRequest(
            name=MODEL_ARMOR_TEMPLATE,
            user_prompt_data={"text": prompt}
        )
        ma_response = ma_client.sanitize_user_prompt(request=ma_request)
        
        if ma_response.sanitization_result.filter_match_state == modelarmor_v1.FilterMatchState.MATCH_FOUND:
            logger.warning(f"Model Armor blocked request. Result: {ma_response.sanitization_result}")
            raise HTTPException(status_code=400, detail="Safety violation detected in your request.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Model Armor validation failed: {e}")
        raise HTTPException(status_code=500, detail="Security validation error")

    try:
        engine = get_agent_engine()
        session = engine.create_session(user_id="web_user")
        session_id = session["id"]

        final_text = ""
        event_count = 0
        for event in engine.stream_query(
            user_id="web_user",
            session_id=session_id,
            message=prompt,
        ):
            event_count += 1
            content = None
            if isinstance(event, dict):
                content = event.get("content")
            elif hasattr(event, "content"):
                content = event.content

            if not content:
                continue

            parts = content.get("parts", []) if isinstance(content, dict) else getattr(content, "parts", [])
            for part in parts:
                text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                if text:
                    logger.info("Event %d: text part (%d chars)", event_count, len(text))
                    final_text += text

        logger.info("Stream complete: %d events, final_text length=%d", event_count, len(final_text))

        if not final_text:
            raise HTTPException(status_code=500, detail="Agent returned no response")

        text = final_text.strip()
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

        trip_plan = json.loads(text)
        return trip_plan

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Agent Engine call failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/geocode")
async def geocode_proxy(q: str, limit: int = Query(5, ge=1, le=10)):
    """Proxy for Nominatim geocoding to avoid CORS issues."""
    if not q:
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required.")
    try:
        # Per Nominatim's usage policy, a custom User-Agent is required.
        # https://operations.osmfoundation.org/policies/nominatim/
        headers = {
            'User-Agent': 'GreenOdyssey/1.0 (https://github.com/GoogleCloudPlatform/gemini-agents-for-firestore)'
        }
        params = {
            "format": "json",
            "q": q,
            "limit": limit,
            "featuretype": "city"
        }
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers=headers,
            timeout=10
        )
        resp.raise_for_status()  # Raise an exception for bad status codes
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Geocoding request failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch data from geocoding service.")


app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=True)
