# services/weather.py
import requests

API_KEY = "01cbb725ab72a40df2dc7deadead0770"  # replace with your key
BASE_URL = "http://api.openweathermap.org/data/2.5/weather"

def get_weather(city: str):
    params = {
        "q": city,
        "appid": API_KEY,
        "units": "metric"   # to get °C instead of Kelvin
    }
    response = requests.get(BASE_URL, params=params)

    if response.status_code == 200:
        data = response.json()
        return {
            "city": data["name"],
            "temp_c": data["main"]["temp"],
            "feels_like": data["main"]["feels_like"],
            "humidity": data["main"]["humidity"],
            "condition": data["weather"][0]["description"],
        }
    else:
        return {"error": response.json().get("message", "API request failed")}

print(get_weather("Bangalore"))
print(get_weather("London"))