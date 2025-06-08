import datetime
import os
import time
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import FastAPI, Request

import asyncio
from aiocache import cached
from dotenv import load_dotenv
import httpx

from aiolimiter import AsyncLimiter

load_dotenv()

aiolimit = AsyncLimiter(20, 4)
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

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


@cached(ttl=10, key_builder=lambda f, *args, **kwargs: f"{args[0]}_{args[1]}")
async def make_osu_request(method: str, endpoint: str, token: str):
    start_no_ratelimit = time.perf_counter()
    async with aiolimit:
        request = httpx.Request(
            method,
            endpoint,
            headers={"Authorization": f"Bearer {token}"}
        )

        async with httpx.AsyncClient() as client:
            start = time.perf_counter()
            resp = await client.send(request)
            end = time.perf_counter()

            print(f"[{datetime.datetime.now().isoformat()}] {method.upper()} {endpoint} "
                  f"({resp.headers.get('x-ratelimit-remaining')}/{resp.headers.get('x-ratelimit-limit')}, {(end - start)*1000:.2f} + {(start - start_no_ratelimit)*1000:.2f}ms)")

            return resp


@app.get("/")
async def root():
    return "hi, go to /multiplayer/rooms/<room_id> to look at a match"

PLAYLIST_KEYS = ["played_at", "id", "beatmap"]

# https://osu.ppy.sh/multiplayer/rooms/1368095
@app.get("/multiplayer/rooms/{room_id}", response_class=HTMLResponse)
async def render_multiplayer_room(request: Request, room_id: str):
    access_token = await get_access_token()

    if access_token is None:
        return Response(status_code=503)

    room_request = await make_osu_request("GET", f"https://osu.ppy.sh/api/v2/rooms/{room_id}", access_token)

    if room_request.status_code != 200:
        return {"error": f"failed to fetch resource: {room_request.status_code}"}

    room_data = room_request.json()

    readable_playlist_items = []

    if "playlist" not in room_data:
        return {"error": "room data did not contain a playlist"}

    tasks = []
    seen_maps = set()

    for playlist_item in room_data["playlist"]:
        # filter playlist items which:
        #   1. has seen the map more than once
        #   2. `played_at == None`
        # these item(s) are playlist items the lobby defaults to after a map is complete.
        # doing it this way will allow for a newly picked map to appear while still filtering out duplicates
        if playlist_item["beatmap_id"] in seen_maps and playlist_item["played_at"] is None:
            print(f"skipping playlist item {playlist_item['id']}, already seen beatmap_id and played_at is null")
            continue

        seen_maps.add(playlist_item["beatmap_id"])

        new_playlist_item = {key: playlist_item[key] for key in PLAYLIST_KEYS}
        task = asyncio.create_task(
            make_osu_request(
                "GET",
                f"https://osu.ppy.sh/api/v2/rooms/{room_id}/playlist/{new_playlist_item['id']}/scores",
                access_token
            )
        )
        tasks.append((task, new_playlist_item))

    for task, new_playlist_item in tasks:
        scores_req = await task
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
                                          "id": room_data["id"],
                                          "starts_at": room_data["starts_at"],
                                          "ends_at": room_data["ends_at"],
                                          "playlists": readable_playlist_items
                                      })
