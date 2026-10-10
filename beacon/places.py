"""Offline place search and navigation math (works with no GPS and no internet).

Data: GeoNames cities with 5,000+ people worldwide (CC BY 4.0), converted by mapdata.py
into maps/places.tsv:  name, ascii, lat, lon, country_code, admin1, country, population
"""
import math
import re
import unicodedata
from pathlib import Path

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    """Initial true bearing (0 = north). Compass needles point to magnetic north;
    local magnetic declination differs — see the navigation card."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass_point(deg: float) -> str:
    return COMPASS[int((deg + 11.25) // 22.5) % 16]


_COORD = re.compile(
    r"^\s*([-+]?\d+(?:\.\d+)?)\s*°?\s*([NSns])?\s*[, ]\s*([-+]?\d+(?:\.\d+)?)\s*°?\s*([EWew])?\s*$")
_DMS = re.compile(r"(\d+)\s*°\s*(\d+)?\s*['′]?\s*(\d+(?:\.\d+)?)?\s*[\"″]?\s*([NSEWnsew])")


def parse_coords(text: str) -> tuple[float, float] | None:
    """'33.75, -84.39'  '33.75N 84.39W'  33°45'N 84°23'W  → (lat, lon)."""
    m = _COORD.match(text)
    if m:
        lat, ns, lon, ew = float(m.group(1)), m.group(2), float(m.group(3)), m.group(4)
        if ns and ns.upper() == "S":
            lat = -abs(lat)
        if ew and ew.upper() == "W":
            lon = -abs(lon)
    else:
        parts = _DMS.findall(text)
        if len(parts) != 2:
            return None
        vals = {}
        for d, mnt, sec, hemi in parts:
            v = float(d) + float(mnt or 0) / 60 + float(sec or 0) / 3600
            hemi = hemi.upper()
            vals["lat" if hemi in "NS" else "lon"] = -v if hemi in "SW" else v
        if len(vals) != 2:
            return None
        lat, lon = vals["lat"], vals["lon"]
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


class Places:
    def __init__(self, tsv_path: str):
        self.rows = []
        p = Path(tsv_path)
        if not p.exists():
            return
        with open(p, encoding="utf-8") as f:
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) < 8:
                    continue
                self.rows.append({"name": c[0], "key": fold(c[1] or c[0]), "lat": float(c[2]),
                                  "lon": float(c[3]), "cc": c[4], "admin1": c[5], "country": c[6],
                                  "pop": int(c[7] or 0)})

    @property
    def available(self) -> bool:
        return bool(self.rows)

    @staticmethod
    def label(r: dict) -> str:
        bits = [r["name"]] + [b for b in (r["admin1"], r["country"]) if b and b != r["name"]]
        return ", ".join(bits)

    def search(self, query: str, limit: int = 8) -> list[dict]:
        coords = parse_coords(query)
        if coords:
            near = self.nearest(*coords, k=1)
            label = f"{coords[0]:.4f}, {coords[1]:.4f}"
            if near:
                label += f" (near {near[0]['name']})"
            return [{"label": label, "lat": coords[0], "lon": coords[1], "exact": True}]
        parts = [fold(p) for p in query.split(",") if p.strip()]
        if not parts:
            return []
        name, rest = parts[0], parts[1:]
        scored = []
        for r in self.rows:
            k = r["key"]
            if k == name:
                rank = 0
            elif k.startswith(name):
                rank = 1
            elif name in k:
                rank = 2
            else:
                continue
            ctx = fold(f"{r['admin1']} {r['country']} {r['cc']}")
            if rest and not all(p in ctx for p in rest):
                continue
            scored.append((rank, -r["pop"], r))
        scored.sort(key=lambda t: (t[0], t[1]))
        return [{"label": self.label(r), "lat": r["lat"], "lon": r["lon"], "pop": r["pop"]}
                for _, _, r in scored[:limit]]

    def nearest(self, lat: float, lon: float, k: int = 5) -> list[dict]:
        if not self.rows:
            return []
        # cheap prefilter on a lat/lon box, widened until enough hits
        for span in (1, 3, 10, 180):
            cand = [r for r in self.rows if abs(r["lat"] - lat) <= span and
                    (abs(r["lon"] - lon) <= span * 1.5 or span == 180)]
            if len(cand) >= k:
                break
        out = sorted(cand, key=lambda r: haversine_km(lat, lon, r["lat"], r["lon"]))[:k]
        return [{"name": self.label(r), "lat": r["lat"], "lon": r["lon"], "pop": r["pop"],
                 "km": round(haversine_km(lat, lon, r["lat"], r["lon"]), 1)} for r in out]


def route_summary(a: dict, b: dict) -> dict:
    """Straight-line facts between two points: distance, bearing and rough travel times."""
    km = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
    brg = bearing_deg(a["lat"], a["lon"], b["lat"], b["lon"])
    road_km = km * 1.3  # roads are rarely straight; ~1.3x is a common rule of thumb
    out = {"km": round(km, 1), "miles": round(km * 0.621371, 1),
           "bearing": round(brg), "compass": compass_point(brg),
           "flight_hours": round(km / 800 + 0.5, 1)}  # cruise ~800 km/h plus climb/descent
    if km <= 2500:  # beyond this, overland estimates stop being meaningful
        out.update(walk_days=round(road_km / 25, 1),   # ~25 km of walking per day with a pack
                   bike_days=round(road_km / 80, 1),
                   drive_hours=round(road_km / 70, 1))  # mixed roads, no traffic or detours
    return out
