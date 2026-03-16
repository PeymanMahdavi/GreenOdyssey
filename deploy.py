"""Deploy the EV Trip Planner agent to Vertex AI Agent Engine."""

import vertexai
from vertexai import agent_engines

PROJECT_ID = "qwiklabs-asl-02-c74cc833bee1"
LOCATION = "us-central1"
STAGING_BUCKET = f"gs://{PROJECT_ID}-staging"


def deploy():
    from ev_trip_planner.agent import root_agent

    client = vertexai.Client(project=PROJECT_ID, location=LOCATION)

    app = agent_engines.AdkApp(agent=root_agent, enable_tracing=True)

    remote_app = client.agent_engines.create(
        agent=app,
        config={
            "display_name": "EV Trip Planner",
            "staging_bucket": STAGING_BUCKET,
            "requirements": [
                "google-adk",
                "google-cloud-aiplatform[adk,agent_engines]",
                "mcp",
            ],
            "env_vars": {
                "GOOGLE_GENAI_USE_VERTEXAI": "True",
                "GOOGLE_CLOUD_PROJECT": PROJECT_ID,
                "GOOGLE_CLOUD_LOCATION": LOCATION,
            },
        },
    )

    print(f"Deployed successfully!")
    print(f"Resource name: {remote_app.api_resource.name}")
    return remote_app


if __name__ == "__main__":
    deploy()
