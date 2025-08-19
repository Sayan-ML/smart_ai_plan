# main.py
from fastapi import FastAPI
from dada import get_weather

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Smart Daily Planner API running 🚀"}

@app.get("/weather/{city}")
def weather(city: str):
    return get_weather(city)
