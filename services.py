import math
from typing import List, Dict, Any
from db import get_vacancies_in_bounds


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_km * c


def find_nearby_vacancies(
    user_lat: float,
    user_lon: float,
    radius_km: int = 5
) -> List[Dict[str, Any]]:
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * max(math.cos(math.radians(user_lat)), 0.01))
    vacancies = get_vacancies_in_bounds(
        min_lat=user_lat - lat_delta,
        max_lat=user_lat + lat_delta,
        min_lon=user_lon - lon_delta,
        max_lon=user_lon + lon_delta,
    )
    result = []

    for vacancy in vacancies:
        distance = haversine(
            user_lat,
            user_lon,
            vacancy["latitude"],
            vacancy["longitude"]
        )

        item = dict(vacancy)
        item["distance"] = round(distance, 2)
        item["in_radius"] = distance <= radius_km
        result.append(item)

    result.sort(key=lambda x: x["distance"])
    return result
