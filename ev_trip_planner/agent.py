import math
import os
from typing import Optional

from google.adk.agents import Agent
from google.adk.tools.google_search_tool import GoogleSearchTool
from pydantic import BaseModel, Field

from .maps_tools import get_directions, search_places, geocode

search_tool = GoogleSearchTool(bypass_multi_tools_limit=True)


# --- Output schema ---


class CarSpecs(BaseModel):
    model: str = Field(description="Full car model name, e.g. 'Tesla Model 3 Long Range'")
    battery_capacity_kwh: float = Field(description="Usable battery capacity in kWh")
    consumption_kwh_per_km: float = Field(description="Energy consumption in kWh per km")
    usable_range_km: float = Field(description="Usable range in km (with 10% buffer)")


class TripStop(BaseModel):
    stop_number: int
    city: str = Field(description="City name with country code, e.g. 'Dortmund, DE'")
    type: str = Field(description="'start', 'charge', 'rest', or 'destination'")
    station_name: Optional[str] = Field(default=None, description="EV charging station name if type is 'charge'")
    station_address: Optional[str] = Field(default=None, description="Station address if type is 'charge'")
    activity: str = Field(description="e.g. 'Start', 'Charge + Rest', 'Rest break', 'Arrive'")
    duration_minutes: Optional[int] = Field(default=None, description="Stop duration in minutes")
    battery_pct: float = Field(description="Battery % at this stop")
    battery_after_pct: Optional[float] = Field(default=None, description="Battery % after charging (only for charge stops)")
    distance_from_start_km: float = Field(description="Distance from start in km")


class TripSummary(BaseModel):
    total_distance_km: float
    total_drive_time_hours: float
    total_trip_time_hours: float = Field(description="Including all stops")
    total_charging_time_minutes: int
    total_rest_time_minutes: int
    charging_stops: int
    rest_stops: int
    tips: list[str] = Field(description="1-3 useful tips for the driver")


class TripPlan(BaseModel):
    start_city: str
    end_city: str
    car: CarSpecs
    stops: list[TripStop]
    summary: TripSummary


# --- Tool functions ---


def calculate_battery_needs(
    total_distance_km: float,
    consumption_kwh_per_km: float,
    battery_capacity_kwh: float,
) -> dict:
    """Calculate whether the EV battery is sufficient for the trip and how many charges are needed.

    Args:
        total_distance_km: Total route distance in kilometers.
        consumption_kwh_per_km: Energy consumption in kWh per kilometer (e.g. 0.18 for 18 kWh/100km).
        battery_capacity_kwh: Total usable battery capacity in kWh.

    Returns:
        A dict with range_km, energy_needed_kwh, charges_needed, and whether the trip is possible on a single charge.
    """
    max_range_km = battery_capacity_kwh / consumption_kwh_per_km
    energy_needed_kwh = total_distance_km * consumption_kwh_per_km
    single_charge_possible = total_distance_km <= max_range_km

    usable_range_km = max_range_km * 0.9
    if usable_range_km <= 0:
        return {
            "max_range_km": round(max_range_km, 1),
            "usable_range_km": 0,
            "energy_needed_kwh": round(energy_needed_kwh, 1),
            "single_charge_possible": False,
            "charges_needed": -1,
            "error": "Usable range is zero or negative. Check battery and consumption values.",
        }

    if single_charge_possible:
        charges_needed = 0
    else:
        remaining_after_first_leg = total_distance_km - usable_range_km
        charges_needed = 1 + int(remaining_after_first_leg // usable_range_km)
        if remaining_after_first_leg % usable_range_km > 0:
            charges_needed = max(charges_needed, 1)

    return {
        "max_range_km": round(max_range_km, 1),
        "usable_range_km": round(usable_range_km, 1),
        "energy_needed_kwh": round(energy_needed_kwh, 1),
        "single_charge_possible": single_charge_possible,
        "charges_needed": charges_needed,
        "battery_capacity_kwh": battery_capacity_kwh,
        "consumption_kwh_per_km": consumption_kwh_per_km,
    }


def plan_all_stops(
    total_distance_km: float,
    usable_range_km: float,
    charges_needed: int,
    battery_capacity_kwh: float,
    consumption_kwh_per_km: float,
    speed_kmh: float,
    max_drive_hours_before_break: float,
) -> dict:
    """Plan all stops for the trip: charging stops AND rest stops, merged together.

    Charging stops and rest stops are combined so the driver doesn't stop twice
    in the same area. If a rest break falls near a charging stop, they are merged
    into a single "charge + rest" stop.

    The agent MUST then use the returned stop distances to find real EV charging
    stations along the route using the search_places tool.

    Args:
        total_distance_km: Total route distance in kilometers.
        usable_range_km: Usable battery range per charge in km (after 10% buffer).
        charges_needed: Number of charging stops required (from calculate_battery_needs).
        battery_capacity_kwh: Total battery capacity in kWh (for charging time calc).
        consumption_kwh_per_km: Energy consumption in kWh per km.
        speed_kmh: Average driving speed in km/h.
        max_drive_hours_before_break: Maximum hours to drive before needing a rest break.

    Returns:
        A dict with a unified list of stops (charge, rest, or charge+rest) and trip totals.
    """
    if speed_kmh <= 0:
        return {"error": "Speed must be greater than zero."}
    if max_drive_hours_before_break <= 0:
        return {"error": "max_drive_hours_before_break must be greater than zero."}

    max_drive_km_before_break = speed_kmh * max_drive_hours_before_break

    charge_distances = []
    if charges_needed > 0:
        segment_length = total_distance_km / (charges_needed + 1)
        if segment_length > usable_range_km:
            segment_length = usable_range_km
        for i in range(1, charges_needed + 1):
            d = round(segment_length * i, 1)
            if d < total_distance_km:
                charge_distances.append(d)

    rest_distances = []
    d = max_drive_km_before_break
    while d < total_distance_km - 20:
        rest_distances.append(round(d, 1))
        d += max_drive_km_before_break

    merge_radius_km = 50
    filtered_rest = []
    for rd in rest_distances:
        near_charge = any(abs(rd - cd) < merge_radius_km for cd in charge_distances)
        if not near_charge:
            filtered_rest.append(rd)

    kwh_to_charge = battery_capacity_kwh * 0.7
    charger_power_kw = 50
    charge_time_min = max(15, math.ceil((kwh_to_charge / charger_power_kw) * 60))

    rest_duration_min = 15

    all_stops = []
    for cd in charge_distances:
        energy_used = cd * consumption_kwh_per_km if cd == charge_distances[0] else (
            (cd - charge_distances[charge_distances.index(cd) - 1]) * consumption_kwh_per_km
        )
        battery_at_arrival_pct = round(
            max(0, (battery_capacity_kwh - energy_used) / battery_capacity_kwh * 100), 0
        )
        all_stops.append({
            "distance_from_start_km": cd,
            "type": "charge",
            "activity": "Charge + Rest",
            "duration_minutes": charge_time_min,
            "battery_at_arrival_pct": battery_at_arrival_pct,
            "battery_after_charge_pct": 80,
        })

    for rd in filtered_rest:
        leg_start = 0
        for s in sorted(all_stops, key=lambda x: x["distance_from_start_km"]):
            if s["distance_from_start_km"] < rd:
                leg_start = s["distance_from_start_km"]
        energy_used = (rd - leg_start) * consumption_kwh_per_km
        battery_start = battery_capacity_kwh if leg_start == 0 else battery_capacity_kwh * 0.8
        battery_pct = round(max(0, (battery_start - energy_used) / battery_capacity_kwh * 100), 0)
        all_stops.append({
            "distance_from_start_km": rd,
            "type": "rest",
            "activity": "Rest break",
            "duration_minutes": rest_duration_min,
            "battery_at_arrival_pct": battery_pct,
        })

    all_stops.sort(key=lambda x: x["distance_from_start_km"])
    for i, stop in enumerate(all_stops):
        stop["stop_number"] = i + 1

    total_drive_hours = round(total_distance_km / speed_kmh, 2)
    total_charge_min = charge_time_min * len(charge_distances)
    total_rest_min = rest_duration_min * len(filtered_rest)
    total_stop_min = total_charge_min + total_rest_min
    total_trip_hours = round(total_drive_hours + total_stop_min / 60, 2)

    return {
        "stops": all_stops,
        "summary": {
            "total_drive_time_hours": total_drive_hours,
            "total_stop_time_minutes": total_stop_min,
            "total_trip_time_hours": total_trip_hours,
            "charging_stops": len(charge_distances),
            "rest_only_stops": len(filtered_rest),
            "charge_time_per_stop_minutes": charge_time_min,
            "rest_time_per_stop_minutes": rest_duration_min,
            "charger_assumption": "50 kW DC fast charger, charging from ~10% to ~80%",
        },
    }


# --- Agent definition ---


AGENT_INSTRUCTION = """\
You are an EV Trip Planner agent. You plan electric vehicle road trips with
REAL, SPECIFIC stops — actual city names, actual charging station names, actual
addresses. Never give generic or approximate stops.

You will receive a trip request with start city, destination city, car model,
and driving preferences. Follow these steps IN ORDER. Do NOT skip any step.
Do NOT produce your final response until ALL steps are complete.

## Step 1: Look Up Car Battery Specs

Use the `google_search` tool to search for the car's specs.
Search for: "<car model> usable battery capacity kWh energy consumption kWh per 100km WLTP"

Extract:
- battery_capacity_kwh: the usable battery capacity in kWh
- consumption_kwh_per_km: energy consumption in kWh per km
  (if you find "X kWh/100km", divide by 100 to get kWh/km)

If the user already provided these values, skip the search.

## Step 2: Get the Route

Use the `get_directions` tool with origin and destination to get the driving route.
Extract: total distance in km, duration, and the list of route steps with
their distances and location descriptions.

Read through ALL route steps. Identify major cities/towns and their approximate
distance from start. You need this in Step 5.

## Step 3: Calculate Battery Needs

Call `calculate_battery_needs` with total_distance_km, consumption_kwh_per_km,
and battery_capacity_kwh.

## Step 4: Plan All Stops

Call `plan_all_stops` with ALL required parameters from previous steps.

## Step 5: Find REAL Charging Stations

For EACH stop with type "charge" in the plan_all_stops result:
1. Find the city/town closest to that stop's distance along the route.
2. Call `search_places` with query "EV charging station" and location set to
   that city (e.g. query="EV charging station", location="Cologne, Germany").
3. Pick the best result — prefer stations near the highway/motorway.
4. Record the station name, full address, and city.

NEVER skip this step. You MUST find real station names for every charging stop.
For rest-only stops, just identify the nearest city from the route.

## Step 6: Produce Final JSON Response

After completing ALL steps above, produce your final response as valid JSON
matching the output schema. Include:
- start_city and end_city
- car specs you found
- ALL stops: start (type "start"), each charge/rest stop, and destination (type "destination")
- summary with totals and 1-3 useful tips

CRITICAL RULES:
- Every stop needs a real city name
- Charging stops need real station_name and station_address from Step 5
- Battery percentages should be realistic based on the calculations
- distance_from_start_km = 0 for start, = total_distance for destination
- A typical 800 km trip should have 3-5 stops, NOT 15
"""

root_agent = Agent(
    name="ev_trip_planner",
    model="gemini-2.5-flash",
    description="Plans EV road trips with real charging stations, auto car spec lookup, and detailed itineraries.",
    instruction=AGENT_INSTRUCTION,
    tools=[
        search_tool,
        get_directions,
        search_places,
        geocode,
        calculate_battery_needs,
        plan_all_stops,
    ],
    output_schema=TripPlan,
)
