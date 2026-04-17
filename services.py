import math
from typing import List, Dict, Any
from db import get_all_vacancies


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Расстояние между двумя точками в километрах.
    """
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
    vacancies = get_all_vacancies()
    result = []

    for vacancy in vacancies:
        distance = haversine(
            user_lat,
            user_lon,
            vacancy["latitude"],
            vacancy["longitude"]
        )

        # 👇 это для диагностики (можешь потом убрать)
        print(
            "VACANCY:",
            vacancy["title"],
            "LAT:", vacancy["latitude"],
            "LON:", vacancy["longitude"],
            "DISTANCE:", distance
        )

        if distance <= radius_km:
            item = dict(vacancy)
            item["distance"] = round(distance, 2)
            result.append(item)

    result.sort(key=lambda x: x["distance"])
    return result