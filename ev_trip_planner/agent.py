import math
import os

from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.tools.google_search_tool import GoogleSearchTool
from mcp import StdioServerParameters

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

maps_tools = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-google-maps"],
            env={"GOOGLE_MAPS_API_KEY": GOOGLE_MAPS_API_KEY},
        ),
        timeout=30,
    ),
)

search_tool = GoogleSearchTool(bypass_multi_tools_limit=True)


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
    stations along the route using maps_search_places.

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

    # --- Compute charging stop distances ---
    charge_distances = []
    if charges_needed > 0:
        segment_length = total_distance_km / (charges_needed + 1)
        if segment_length > usable_range_km:
            segment_length = usable_range_km
        for i in range(1, charges_needed + 1):
            d = round(segment_length * i, 1)
            if d < total_distance_km:
                charge_distances.append(d)

    # --- Compute rest stop distances (independent of charging) ---
    rest_distances = []
    d = max_drive_km_before_break
    while d < total_distance_km - 20:
        rest_distances.append(round(d, 1))
        d += max_drive_km_before_break

    # --- Merge: remove rest stops within 50 km of a charging stop ---
    merge_radius_km = 50
    filtered_rest = []
    for rd in rest_distances:
        near_charge = any(abs(rd - cd) < merge_radius_km for cd in charge_distances)
        if not near_charge:
            filtered_rest.append(rd)

    # --- Charging time estimate (correct math: kWh, not km) ---
    # Charge from ~10% to ~80% = 70% of battery
    kwh_to_charge = battery_capacity_kwh * 0.7
    charger_power_kw = 50
    charge_time_min = max(15, math.ceil((kwh_to_charge / charger_power_kw) * 60))

    rest_duration_min = 15

    # --- Build unified stop list sorted by distance ---
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

## Step 1: Collect Inputs

You need:
- Start point and end point (city, address, or coordinates)
- Car model (e.g. "Tesla Model 3 Long Range", "VW ID.4 Pro")
- Average driving speed (km/h) — assume 100 km/h highway average if not given
- Preferred max driving time before breaks (hours) — assume 2 hours if not given

You do NOT need the user to provide battery capacity or consumption.
If the user gives a car model, YOU look up the specs yourself (see Step 2).
If the user only says a car brand without a specific model, ask which model/variant.

## Step 2: Look Up Car Battery Specs

When the user provides a car model name, use the `google_search` tool to search
for its specs. Search for: "<car model> usable battery capacity kWh energy consumption kWh per 100km WLTP"

From the search results, extract:
- **battery_capacity_kwh**: the usable battery capacity in kWh
- **consumption_kwh_per_km**: energy consumption in kWh per km
  (if you find "X kWh/100km", divide by 100 to get kWh/km)

Tell the user what specs you found before proceeding.
If the user provides battery_capacity_kwh and consumption directly, skip the search.

## Step 3: Get the Route

Use `maps_directions` to get the route from start to end.
From the response, extract:
- Total distance in km
- Total estimated driving duration
- **The list of route steps with their distances and location descriptions**

IMPORTANT: Read through ALL the route steps. Identify the major cities and towns
the route passes through, and note approximately how far each is from the start.
You will need this list in Step 5 to find charging stations.

## Step 4: Calculate Battery Needs

Call `calculate_battery_needs` with total_distance_km, consumption_kwh_per_km,
and battery_capacity_kwh.

## Step 5: Plan All Stops

Call `plan_all_stops` with ALL required parameters from steps 3-4:
- total_distance_km, usable_range_km, charges_needed (from step 4)
- battery_capacity_kwh, consumption_kwh_per_km (from step 2)
- speed_kmh, max_drive_hours_before_break (from step 1)

This gives you a unified list of stops (charging and rest combined).
Charging stops near rest stops are already merged — no duplicates.

## Step 6: Find REAL Charging Stations

For EACH stop that has type "charge" in the plan_all_stops result:
1. Look at the route steps from Step 3. Find the city or town closest to
   that stop's distance_from_start_km.
2. Call `maps_search_places` with query "EV charging station" and location
   set to that city (e.g. "EV charging station near Kassel, Germany").
3. Pick the best result — prefer stations near the highway/motorway.
4. Record the station name, full address, and city.

NEVER skip this step. NEVER present "search for charging stations near this point".
You MUST present real station names and addresses for every charging stop.

For rest-only stops, just identify the nearest city from the route steps.

## Step 7: Present the Final Itinerary

Present a DETAILED itinerary table. Example format:

**Route: Amsterdam → Munich (828 km, ~8.3h driving)**
**Car: Tesla Model 3 Long Range (75 kWh, 0.16 kWh/km, ~420 km range)**

| # | City | Charging Station | Activity | Duration | Battery |
|---|------|------------------|----------|----------|---------|
| 1 | Dortmund, DE | Ionity Ladepark, Raststätte Lichtendorf | Charge + Rest | 45 min | 18% → 80% |
| 2 | Würzburg, DE | - | Rest break | 15 min | 52% |
| 3 | Nuremberg, DE | EnBW Schnellladepark, Ingolstädter Str. | Charge | 45 min | 15% → 80% |
| 4 | Munich, DE | Destination | Arrive | - | 35% |

Below the table include:
- Total trip time (driving + all stops)
- Total charging time vs rest time
- Tips (e.g. "your car supports 150kW fast charging — actual charge time may be shorter")

IMPORTANT: A typical trip of 800 km should have 3-5 total stops, NOT 15.
Charging stops double as rest stops. Only add separate rest stops if the
driving gap between two charging stops exceeds the driver's max drive time.

## Important Rules

- Always keep a 10% battery buffer — never arrive at a charger below 10%
- Use metric units (km, kWh) throughout
- Be precise: real station names, real cities, real addresses
- If no EV charging station is found near a stop, search a wider area or the
  next city along the route
- Charging stops count as rest stops — do NOT add a separate rest stop next
  to a charging stop
"""

root_agent = Agent(
    name="ev_trip_planner",
    model="gemini-2.5-flash-lite",
    description="Plans EV road trips with real charging stations, auto car spec lookup, and detailed itineraries.",
    instruction=AGENT_INSTRUCTION,
    tools=[
        maps_tools,
        search_tool,
        calculate_battery_needs,
        plan_all_stops,
    ],
)
