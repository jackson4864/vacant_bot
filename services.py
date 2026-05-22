import math
from typing import Any, Dict, List, Optional

from db import get_vacancies_in_bounds


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(dlambda / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return earth_radius_km * c


def find_nearest_vacancies(
    user_lat: float,
    user_lon: float,
    vacancies: List[Dict[str, Any]],
    radius_km: int = 10,
    limit: Optional[int] = 5,
) -> List[Dict[str, Any]]:
    result = []

    for vacancy in vacancies:
        distance = haversine(
            user_lat,
            user_lon,
            vacancy["latitude"],
            vacancy["longitude"]
        )

        if distance <= radius_km:
            vacancy["distance"] = round(distance, 2)
            result.append(vacancy)

    result = sorted(result, key=lambda x: x["distance"])

    if limit is None:
        return result
    return result[:limit]


def find_nearby_vacancies(
    user_lat: float,
    user_lon: float,
    radius_km: int = 10,
    limit: Optional[int] = 5,
) -> List[Dict[str, Any]]:
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * max(math.cos(math.radians(user_lat)), 0.01))
    vacancies = get_vacancies_in_bounds(
        min_lat=user_lat - lat_delta,
        max_lat=user_lat + lat_delta,
        min_lon=user_lon - lon_delta,
        max_lon=user_lon + lon_delta,
    )
    return find_nearest_vacancies(
        user_lat=user_lat,
        user_lon=user_lon,
        vacancies=vacancies,
        radius_km=radius_km,
        limit=limit,
    )
