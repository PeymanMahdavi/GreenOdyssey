import os

import requests

MAPS_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
BASE = "https://maps.googleapis.com/maps/api"


def get_directions(origin: str, destination: str) -> dict:
    """Get driving directions and route details between two locations.

    Args:
        origin: Starting location (city name, address, or coordinates).
        destination: Ending location (city name, address, or coordinates).

    Returns:
        A dict with route legs, distance, duration, and step-by-step directions.
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
    return resp.json()


def search_places(query: str, location: str) -> dict:
    """Search for places (e.g. EV charging stations) near a specific location.

    Args:
        query: What to search for, e.g. 'EV charging station'.
        location: City or address to search near, e.g. 'Cologne, Germany'.

    Returns:
        A dict with a list of matching places including names and addresses.
    """
    resp = requests.get(
        f"{BASE}/place/textsearch/json",
        params={
            "query": f"{query} near {location}",
            "key": MAPS_KEY,
        },
        timeout=30,
    )
    return resp.json()


def geocode(address: str) -> dict:
    """Convert an address or place name to geographic coordinates.

    Args:
        address: The address or place name to geocode.

    Returns:
        A dict with latitude/longitude results.
    """
    resp = requests.get(
        f"{BASE}/geocode/json",
        params={
            "address": address,
            "key": MAPS_KEY,
        },
        timeout=30,
    )
    return resp.json()
