import os, requests
from math import radians, cos, sin, asin, sqrt

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 1000 * (2 * R * asin(sqrt(a))) 

def get_user_location_google(api_key: str):
    url = f"https://www.googleapis.com/geolocation/v1/geolocate?key={api_key}"
    try:
        resp = requests.post(url, timeout=10).json()
        return resp.get("location", {"lat": None, "lng": None})
    except Exception:
        return {"lat": None, "lng": None}

def get_nearby_places(api_key: str, lat: float, lon: float, place_type="restaurant", radius=2000):
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "key": api_key,
        "location": f"{lat},{lon}",
        "radius": radius,
        "type": place_type
    }
    try:
        resp = requests.get(url, params=params, timeout=10).json()
    except Exception:
        return []

    if resp.get("status") != "OK":
        return []

    places = []
    for p in resp.get("results", []):
        place_id = p.get("place_id")
        maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else None
        places.append({
            "name": p.get("name"),
            "lat": p["geometry"]["location"]["lat"],
            "lon": p["geometry"]["location"]["lng"],
            "rating": p.get("rating", "N/A"),
            "address": p.get("vicinity", "No address"),
            "photo": p["photos"][0]["photo_reference"] if "photos" in p else None,
            "url": maps_url
        })
    return places