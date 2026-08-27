"""OSM 矢量要素获取：道路/水系/地名（Overpass API，首次在线缓存后离线）。

用途：评估图的地理底图叠加，让用户辨识位置（哪条路、哪条河）。
查询失败不阻塞评估——返回空结果，页面仅少了底图层。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "osm"

_OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# 主干道用粗线，其余细线
ROAD_MAJOR = {"motorway", "trunk", "primary", "secondary"}
ROAD_MINOR = {"tertiary", "residential", "unclassified", "living_street", "service"}

_QUERY = """
[out:json][timeout:60];
(
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street)$"]({s},{w},{n},{e});
  way["waterway"~"^(river|stream|canal|drain)$"]({s},{w},{n},{e});
  node["place"~"^(suburb|neighbourhood|quarter|city|town)$"]({s},{w},{n},{e});
);
out body geom;
"""


def fetch_osm(bbox: tuple[float, float, float, float], offline: bool = False) -> dict:
    """取 bbox=(west, south, east, north) 的道路/水系/地名。

    返回 {roads: [[ [lon,lat],... ]], road_major: [[...]...], waterways: [[...]],
          places: [[lon, lat, name]]}；无数据/失败返回空结构。
    """
    west, south, east, north = bbox
    cache = CACHE_DIR / f"osm_{west:.3f}_{south:.3f}_{east:.3f}_{north:.3f}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    if offline:
        return {"roads": [], "road_major": [], "waterways": [], "places": []}

    q = _QUERY.format(w=west, s=south, e=east, n=north)
    data = None
    for base in _OVERPASS_URLS:
        try:
            req = urllib.request.Request(
                base, data=f"data={urllib.parse.quote(q)}".encode(),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "swmm-copilot/0.2 (open-source urban flood assessment tool)",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read())
            break
        except Exception as e:
            print(f"Overpass {base} 失败：{e}")
    if data is None:
        return {"roads": [], "road_major": [], "waterways": [], "places": []}

    roads, road_major, waterways, places = [], [], [], []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        if "place" in tags and tags.get("name") and "lon" in el:  # node 无 geometry 键
            places.append([el["lon"], el["lat"], tags["name"]])
            continue
        geom = el.get("geometry")
        if not geom:
            continue
        coords = [[p["lon"], p["lat"]] for p in geom]
        hw = tags.get("highway")
        if hw:
            (road_major if hw in ROAD_MAJOR else roads).append(coords)
        elif "waterway" in tags:
            waterways.append(coords)
        elif "place" in tags and tags.get("name"):
            places.append([el["lon"], el["lat"], tags["name"]])
    out = {"roads": roads, "road_major": road_major, "waterways": waterways, "places": places}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"OSM 底图要素：主干道 {len(road_major)}、一般道路 {len(roads)}、水系 {len(waterways)}、地名 {len(places)}")
    return out
