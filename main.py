import datetime
import os
from fastapi.responses import HTMLResponse

from fastapi.templating import Jinja2Templates

from fastapi import FastAPI, Request
from aiocache import cached
from dotenv import load_dotenv
import httpx

from aiolimiter import AsyncLimiter

load_dotenv()

aiolimit = AsyncLimiter(120, 60)
app = FastAPI()
templates = Jinja2Templates(directory="templates")


@cached(key="osu_token", ttl=3600)
async def get_access_token():
    access_key = os.getenv("OSU_ACCESS_KEY")
    access_secret = os.getenv("OSU_ACCESS_SECRET")

    if access_key is None or access_secret is None:
        print("missing access or secret key")
        return None

    token_endpoint = "https://osu.ppy.sh/oauth/token"

    async with httpx.AsyncClient() as client:
        resp = await client.post(token_endpoint,
                         auth=(access_key, access_secret),
                         data={
                             "grant_type": "client_credentials",
                             "scope": "public"
                         })

        if resp.status_code not in range(200, 300):
            print(f"token response returned {resp.status_code}")
            return None

        return resp.json()["access_token"]


@cached(ttl=3600, key_builder=lambda f, *args, **kwargs: f"{args[0]}_{args[1]}")
async def make_osu_request(method: str, endpoint: str, token: str):
    async with aiolimit:
        request = httpx.Request(
            method,
            endpoint,
            headers={"Authorization": f"Bearer {token}"}
        )

        print(f"[{datetime.datetime.now().isoformat()}] {method.upper()} {endpoint}")

        async with httpx.AsyncClient() as client:
            return await client.send(request)

@app.get("/")
async def root():
    return {"message": "hi, go to /multiplayer/rooms/<room_id> to look at a match"}

PLAYLIST_KEYS = ["played_at", "id", "beatmap"]

# https://osu.ppy.sh/multiplayer/rooms/1368095
@app.get("/multiplayer/rooms/{room_id}", response_class=HTMLResponse)
async def render_multiplayer_room(request: Request, room_id: str):
    access_token = await get_access_token()

    room_request = await make_osu_request("GET", f"https://osu.ppy.sh/api/v2/rooms/{room_id}", access_token)

    if room_request.status_code != 200:
        return {"error": f"failed to fetch resource: {room_request.status_code}"}

    room_data = room_request.json()

    readable_playlist_items = []

    if "playlist" not in room_data:
        return {"error": "room data did not contain a playlist"}

    for playlist_item in room_data["playlist"]:
        new_playlist_item = {key: playlist_item[key] for key in PLAYLIST_KEYS}

        scores_req = await make_osu_request("GET",
                                      f"https://osu.ppy.sh/api/v2/rooms/{room_id}/playlist/{new_playlist_item['id']}/scores",
                                      access_token)

        if scores_req.status_code != 200:
            scores = {"error": f"failed fetching scores "
                               f"for playlist {new_playlist_item['id']}: {scores_req.status_code}"}
        else:
            scores = scores_req.json()["scores"]


        new_playlist_item["scores"] = scores

        readable_playlist_items.append(new_playlist_item)

    return templates.TemplateResponse(request=request,
                                      name="room.html",
                                      context={
                                          "name": room_data["name"],
                                          "playlists": readable_playlist_items
                                      })
