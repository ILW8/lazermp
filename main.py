import os

from fastapi import FastAPI
import cachetools.func
from dotenv import load_dotenv
import requests


load_dotenv()

app = FastAPI()


@cachetools.func.ttl_cache(maxsize=1, ttl=3600)
async def get_access_token_cached():
    return await get_access_token()


async def get_access_token():
    access_key = os.getenv("OSU_ACCESS_KEY")
    access_secret = os.getenv("OSU_ACCESS_SECRET")

    if access_key is None or access_secret is None:
        print("missing access or secret key")
        return None

    token_endpoint = "https://osu.ppy.sh/oauth/token"

    resp = requests.post(token_endpoint,
                         auth=(access_key, access_secret),
                         data={
                             "grant_type": "client_credentials",
                             "scope": "public"
                         })

    if resp.status_code not in range(200, 300):
        print(f"token response returned {resp.status_code}")
        return None

    return resp.json()["access_token"]


async def make_osu_request(endpoint: str, payload: dict):
    pass


@app.get("/")
async def root():
    return {"message": "hi, go to /multiplayer/rooms/<room_id> to look at a match"}

# https://osu.ppy.sh/multiplayer/rooms/1368095
@app.get("/multiplayer/rooms/{room_id}")
async def say_hello(room_id: str):
    return {"message": f"Hello {room_id}"}
