"""Deploy the EV Trip Planner agent to Vertex AI Agent Engine."""

from google.api_core import exceptions
from google.api_core.client_options import ClientOptions
import vertexai
from google.cloud import modelarmor_v1
from vertexai import agent_engines

PROJECT_ID = "qwiklabs-asl-02-c74cc833bee1"
LOCATION = "us-central1"
STAGING_BUCKET = f"gs://{PROJECT_ID}-staging"

GOOGLE_MAPS_API_KEY = "AIzaSyCusFvFHfognHFDGDQueMDye04d1kQk4BA"

TEMPLATE_ID = "green-odyssey-safety"


def create_armor_template():
    from google.cloud import modelarmor_v1

    client = modelarmor_v1.ModelArmorClient(
        transport="rest",
        client_options=ClientOptions(
            api_endpoint=f"modelarmor.{LOCATION}.rep.googleapis.com"
        ),
    )

    template = modelarmor_v1.Template(
        filter_config=modelarmor_v1.FilterConfig(
            rai_settings=modelarmor_v1.RaiFilterSettings(
                rai_filters=[
                    modelarmor_v1.RaiFilterSettings.RaiFilter(
                        filter_type=modelarmor_v1.RaiFilterType.DANGEROUS,
                        confidence_level=modelarmor_v1.DetectionConfidenceLevel.MEDIUM_AND_ABOVE,
                    ),
                    modelarmor_v1.RaiFilterSettings.RaiFilter(
                        filter_type=modelarmor_v1.RaiFilterType.HATE_SPEECH,
                        confidence_level=modelarmor_v1.DetectionConfidenceLevel.MEDIUM_AND_ABOVE,
                    ),
                    modelarmor_v1.RaiFilterSettings.RaiFilter(
                        filter_type=modelarmor_v1.RaiFilterType.SEXUALLY_EXPLICIT,
                        confidence_level=modelarmor_v1.DetectionConfidenceLevel.MEDIUM_AND_ABOVE,
                    ),
                    modelarmor_v1.RaiFilterSettings.RaiFilter(
                        filter_type=modelarmor_v1.RaiFilterType.HARASSMENT,
                        confidence_level=modelarmor_v1.DetectionConfidenceLevel.MEDIUM_AND_ABOVE,
                    ),
                ],
            ),
            pi_and_jailbreak_filter_settings=modelarmor_v1.PiAndJailbreakFilterSettings(
                filter_enforcement=modelarmor_v1.PiAndJailbreakFilterSettings.PiAndJailbreakFilterEnforcement.ENABLED,
                confidence_level=modelarmor_v1.DetectionConfidenceLevel.LOW_AND_ABOVE,
            ),
            malicious_uri_filter_settings=modelarmor_v1.MaliciousUriFilterSettings(
                filter_enforcement=modelarmor_v1.MaliciousUriFilterSettings.MaliciousUriFilterEnforcement.ENABLED,
            ),
        ),
    )

    request = modelarmor_v1.CreateTemplateRequest(
        parent=f"projects/{PROJECT_ID}/locations/{LOCATION}",
        template_id=TEMPLATE_ID,
        template=template,
    )

    try:
        response = client.create_template(request=request)
        print(f"Created Model Armor template: {response.name}")
    except (exceptions.AlreadyExists, exceptions.Conflict):
        print(f"Model Armor template already exists: {TEMPLATE_ID}")


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
    deploy()
