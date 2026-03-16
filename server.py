import os
import uuid
import logging

from dotenv import load_dotenv
load_dotenv("ev_trip_planner/.env")

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ev_trip_planner.agent import root_agent, TripPlan

logger = logging.getLogger(__name__)

APP_NAME = "ev_trip_planner_app"
session_service = InMemorySessionService()
runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(lifespan=lifespan)


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

    user_id = "web_user"
    session_id = str(uuid.uuid4())

    try:
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )

        final_text = ""
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=prompt)]
            ),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        final_text += part.text

        if not final_text:
            raise HTTPException(status_code=500, detail="Agent returned no response")

        trip_plan = TripPlan.model_validate_json(final_text)
        return trip_plan.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Agent execution failed")
        raise HTTPException(status_code=500, detail=str(e))


app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
