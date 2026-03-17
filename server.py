import os
import json
import logging
import re

import vertexai
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
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

client = vertexai.Client(project=PROJECT_ID, location=LOCATION)
agent_engine = None


def get_agent_engine():
    global agent_engine
    if agent_engine is None:
        if not AGENT_ENGINE_RESOURCE_NAME:
            raise RuntimeError("AGENT_ENGINE_RESOURCE_NAME env var is not set")
        agent_engine = client.agent_engines.get(name=AGENT_ENGINE_RESOURCE_NAME)
    return agent_engine


app = FastAPI()


class PlanTripRequest(BaseModel):
    start_city: str
    dest_city: str
    car_brand: str
    car_model: str
    travel_style: str = "balanced"
    trip_mood: str = "relaxed"
    speed_kmh: float = 100.0
    max_drive_hours: float = 2.0


@app.post("/api/plan-trip")
async def plan_trip(request: PlanTripRequest):
    car_full = f"{request.car_brand} {request.car_model}".strip()

    prompt = (
        f"Plan an EV road trip from {request.start_city} to {request.dest_city}. "
        f"Car: {car_full}. "
        f"Average speed: {request.speed_kmh} km/h. "
        f"Max driving before a break: {request.max_drive_hours} hours. "
        f"Travel style: {request.travel_style}. "
    )

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


app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
