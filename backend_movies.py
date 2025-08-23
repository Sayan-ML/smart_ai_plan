import requests

def get_genres(api_key):
    url = "https://api.themoviedb.org/3/genre/movie/list"
    params = {"api_key": api_key, "language": "en-US"}
    res = requests.get(url, params=params, timeout=10)
    if res.status_code != 200:
        return {}
    data = res.json().get("genres", [])
    return [{"id": g["id"], "name": g["name"]} for g in data]

def discover_movies(api_key, genre_ids=None, year=None, language=None, num_results=10):
    url = "https://api.themoviedb.org/3/discover/movie"
    params = {"api_key": api_key, "sort_by": "popularity.desc", "page": 1}

    if genre_ids:
        if isinstance(genre_ids, int):
            genre_ids = [genre_ids]
        params["with_genres"] = ",".join(map(str, genre_ids))

    if year:
        params["primary_release_year"] = year
    if language and language != "Any":
        params["with_original_language"] = language

    res = requests.get(url, params=params, timeout=10)
    res.raise_for_status()
    data = res.json()
    return data.get("results", [])[:num_results]
