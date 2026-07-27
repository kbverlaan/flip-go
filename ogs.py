"""OGS REST-laag. Publieke endpoints werken zonder auth;
inloggen (OAuth2/PKCE) en de realtime socket komen hierna.
"""
import requests

BASE = "https://online-go.com/api/v1"
UA = {"User-Agent": "flip-go/0.1 (personal client)"}


def get_player(username):
    r = requests.get(f"{BASE}/players", params={"username": username},
                     headers=UA, timeout=10)
    r.raise_for_status()
    res = r.json().get("results", [])
    return res[0] if res else None


def rating_to_rank(rating):
    """OGS: rank = ln(rating/525) * 23.15; <30k afkappen."""
    import math
    if not rating:
        return "?"
    r = math.log(rating / 525) * 23.15
    return f"{int(30 - r)}k" if r < 30 else f"{int(r - 29)}d"
