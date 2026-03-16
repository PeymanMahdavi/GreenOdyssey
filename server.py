import os
from dotenv import load_dotenv
load_dotenv()

# Sanity check: Fail fast if no LLM authentication is found
if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_GENAI_USE_VERTEXAI"):
    raise RuntimeError("Missing GEMINI_API_KEY or Vertex AI config. Please check your .env file.")

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ev_trip_planner.agent import root_agent

# Set up ADK session service and runner
session_service = InMemorySessionService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Explicitly create the default session asynchronously before the server starts
    await session_service.create_session(
        app_name="ev_trip_planner_app",
        user_id="default_user",
        session_id="default_session"
    )
    yield

app = FastAPI(lifespan=lifespan)

runner = Runner(
    agent=root_agent,
    app_name="ev_trip_planner_app",
    session_service=session_service
)

class ChatRequest(BaseModel):
    message: str

@app.post("/api/chat")
def chat_with_agent(request: ChatRequest):
    content = types.Content(role="user", parts=[types.Part(text=request.message)])
    reply_text = "No response received."

    # Run the agent and iterate through the events to find the final response
    for event in runner.run(user_id="default_user", session_id="default_session", new_message=content):
        if event.is_final_response():
            reply_text = event.content.parts[0].text
            break
    
    return {"reply": reply_text}

# Mount the "stitch" directory to serve your exported UI (e.g., index.html)
app.mount("/", StaticFiles(directory="stitch", html=True), name="ui")

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)