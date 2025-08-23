import requests
from datetime import datetime

BASE_URL = "http://api.mediastack.com/v1/news"

def get_today_news(api_key: str, limit: int = 10):

    today = datetime.utcnow().strftime("%Y-%m-%d")
    params = {
        "access_key": api_key,
        "countries": "in",
        "limit": limit,
        "date": today
    }

    resp = requests.get(BASE_URL, params=params)
    data = resp.json()

    if data.get("data"):
        return data["data"]
    raise Exception(f"Error fetching news: {data.get('error', 'Unknown')}")