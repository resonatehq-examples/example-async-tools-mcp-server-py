from __future__ import annotations

import calendar
import json
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator

import requests
from fastmcp import FastMCP
from resonate.resonate import Resonate

if TYPE_CHECKING:
    from resonate.context import Context


# Resonate instance is created inside the server lifespan so it starts within
# the running asyncio event loop that FastMCP / uvicorn provides.
resonate: Resonate | None = None


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    global resonate
    resonate = Resonate(url=os.environ.get("RESONATE_URL", "http://localhost:8001"))
    resonate.register(weather_data)
    yield


mcp = FastMCP("timer", lifespan=lifespan)


async def weather_data(ctx: Context, latitude, longitude, year, month, timezone="America/Edmonton"):
    print(f"Weather data gathering started for {latitude}, {longitude} in {year}-{month} ({timezone})")
    year = int(year)
    month = int(month)
    longitude = float(longitude)
    latitude = float(latitude)

    start_date = f"{year}-{month:02d}-01"
    end_day = calendar.monthrange(year, month)[1]
    end_date = f"{year}-{month:02d}-{end_day}"
    timezone = "America/Edmonton"
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": timezone
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


@mcp.tool()
def start_gathering(latitude, longitude, year, month, timezone="America/Edmonton"):
    """
    Start a weather data gathering job.

    Args:
        latitude (float): The latitude of the location.
        longitude (float): The longitude of the location.
        year (int): The year for which to gather data.
        month (int): The month for which to gather data.

    Returns:
        dict: A dictionary containing the name of the job.
        This can be used to probe the status of the job or await its result.
    """
    job_name = f"weather_data_{latitude}_{longitude}_{year}_{month}"
    resonate.run(job_name, weather_data, latitude, longitude, year, month)
    return {"job_name": job_name}


@mcp.tool()
async def probe_status(job_names):
    """
    Probe for the status of a data gathering jobs.

    Args:
        job_names [(str), ...]: The names of the jobs.

    Returns:
        statuses [(dict), ...]: An array of dictionaries containing the status of the jobs, either "running" or "complete".
    """
    if isinstance(job_names, str):
        try:
            job_names = json.loads(job_names)
        except json.JSONDecodeError:
            return {"error": "Invalid JSON for job_names"}

    print(f"Probing status for jobs: {job_names}")
    statuses = []
    for job_name in job_names:
        if isinstance(job_name, dict):
            job_name = job_name.get("job_name", "")
        handle = await resonate.get(job_name)
        if not handle.done():
            statuses.append({"job_name": job_name, "status": "running"})
        else:
            statuses.append({"job_name": job_name, "status": await handle.result()})
    return statuses


@mcp.tool()
async def await_result(job_names):
    """
    Wait for the result of a weather data gathering jobs by their names.

    Args:
        job_names [(str), ...]: The names of the jobs.

    Returns:
        dict: A dictionary containing the results of the jobs.
    """
    if isinstance(job_names, str):
        try:
            job_names = json.loads(job_names)
        except json.JSONDecodeError:
            return {"error": "Invalid JSON for job_names"}

    print(f"Awaiting results for jobs: {job_names}")
    results = {}
    for job_name in job_names:
        if isinstance(job_name, dict):
            job_name = job_name.get("job_name", "")
        handle = await resonate.get(job_name)
        results[job_name] = await handle.result()
    return results


def main():
    mcp.run(transport='streamable-http', host='127.0.0.1', port=5001)


if __name__ == "__main__":
    main()
