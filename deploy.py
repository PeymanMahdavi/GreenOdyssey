"""Deploy the EV Trip Planner agent to Vertex AI Agent Engine."""

from google.api_core import exceptions
import vertexai
from google.cloud import modelarmor_v1
from vertexai import agent_engines

PROJECT_ID = "qwiklabs-asl-02-c74cc833bee1"
LOCATION = "us-central1"
STAGING_BUCKET = f"gs://{PROJECT_ID}-staging"

GOOGLE_MAPS_API_KEY = "AIzaSyCusFvFHfognHFDGDQueMDye04d1kQk4BA"


def create_armor_template():
    client = modelarmor_v1.ModelArmorClient()

    template = {
        "name": "green-odyssey-safety",
        "prompt_injection_filter": {"enabled": True},
        "data_loss_prevention_filter": {"enabled": True},
    }

    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"

    try:
        response = client.create_template(
            parent=parent,
            template_id="green-odyssey-safety",
            template=template,
        )
        print(response)
    except exceptions.AlreadyExists:
        print("Template already exists.")


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
                "requests",
                "pydantic",
                "cloudpickle",
            ],
            "extra_packages": ["./ev_trip_planner"],
            "env_vars": {
                "GOOGLE_GENAI_USE_VERTEXAI": "True",
                "GOOGLE_MAPS_API_KEY": GOOGLE_MAPS_API_KEY,
            },
        },
    )

    print("Deployed successfully!")
    print(f"Resource name: {remote_app.api_resource.name}")
    return remote_app


if __name__ == "__main__":
    try:
        create_armor_template()
    except Exception as e:
        print(f"Model Armor template creation skipped: {e}")
    deploy()
