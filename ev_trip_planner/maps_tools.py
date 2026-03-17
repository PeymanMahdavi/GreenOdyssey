import os

import requests

MAPS_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
BASE = "https://maps.googleapis.com/maps/api"


def _summarize_step(step: dict) -> dict:
    """Extract only the fields the agent needs from a directions step."""
    summary = {
        "distance_km": round(step["distance"]["value"] / 1000, 1),
        "duration_min": round(step["duration"]["value"] / 60, 1),
        "start": step["start_location"],
        "end": step["end_location"],
    }
    instructions = step.get("html_instructions", "")
    import re
    summary["instruction"] = re.sub(r"<[^>]+>", "", instructions)
    return summary


def get_directions(origin: str, destination: str) -> dict:
    """Get driving directions and route details between two locations.

    Args:
        origin: Starting location (city name, address, or coordinates).
        destination: Ending location (city name, address, or coordinates).

    Returns:
        A dict with total distance/duration and major waypoints along the route.
    """
    resp = requests.get(
        f"{BASE}/directions/json",
        params={
            "origin": origin,
            "destination": destination,
            "mode": "driving",
            "key": MAPS_KEY,
        },
        timeout=30,
    )
    data = resp.json()

    if data.get("status") != "OK" or not data.get("routes"):
        return {"status": data.get("status", "UNKNOWN"), "error": "No route found"}

    route = data["routes"][0]
    leg = route["legs"][0]

    steps = leg.get("steps", [])
    major_steps = []
    cumulative_km = 0.0
    for s in steps:
        step_km = s["distance"]["value"] / 1000
        cumulative_km += step_km
        if step_km >= 5:
            info = _summarize_step(s)
            info["cumulative_km"] = round(cumulative_km, 1)
            major_steps.append(info)

    return {
        "status": "OK",
        "start_address": leg["start_address"],
        "end_address": leg["end_address"],
        "total_distance_km": round(leg["distance"]["value"] / 1000, 1),
        "total_duration_text": leg["duration"]["text"],
        "total_duration_minutes": round(leg["duration"]["value"] / 60, 1),
        "major_steps": major_steps,
    }


def search_places(query: str, location: str) -> dict:
    """Search for places (e.g. EV charging stations) near a specific location.

    Args:
        query: What to search for, e.g. 'EV charging station'.
        location: City or address to search near, e.g. 'Cologne, Germany'.

    Returns:
        A dict with up to 5 matching places including names and addresses.
    """
    resp = requests.get(
        f"{BASE}/place/textsearch/json",
        params={
            "query": f"{query} near {location}",
            "key": MAPS_KEY,
        },
        timeout=30,
    )
    data = resp.json()

    if data.get("status") != "OK":
        return {"status": data.get("status", "UNKNOWN"), "results": []}

    places = []
    for r in data.get("results", [])[:5]:
        places.append({
            "name": r.get("name"),
            "address": r.get("formatted_address"),
            "rating": r.get("rating"),
            "location": r.get("geometry", {}).get("location"),
            "open_now": r.get("opening_hours", {}).get("open_now"),
        })

    return {"status": "OK", "results": places}


def geocode(address: str) -> dict:
    """Convert an address or place name to geographic coordinates.

    Args:
        address: The address or place name to geocode.

    Returns:
        A dict with latitude and longitude.
    """
    resp = requests.get(
        f"{BASE}/geocode/json",
        params={
            "address": address,
            "key": MAPS_KEY,
        },
        timeout=30,
    )
    data = resp.json()

    if data.get("status") != "OK" or not data.get("results"):
        return {"status": data.get("status", "UNKNOWN"), "error": "Not found"}

    result = data["results"][0]
    return {
        "status": "OK",
        "formatted_address": result.get("formatted_address"),
        "location": result["geometry"]["location"],
    }
