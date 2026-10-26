"""Pure calculation layer for the ECALC proof of concept (WGS-84)."""
from __future__ import annotations

from dataclasses import dataclass
import html
import math
import re

from geographiclib.geodesic import Geodesic

AIRPORTS = {
    "UCFM (Манас / Бишкек)": "N430341 E0742839",
    "UCFO (Ош)": "N403632 E0724735",
    "UCFB (Баткен)": "N400235 E0705016",
    "UCFV (Кербен)": "N412903 E0714402",
    "UCFT (Талас)": "N423101 E0721448",
    "UCFZ (Казарман)": "N412423 E0740149",
    "UCFN (Нарын)": "N412604 E0760706",
    "UCFL (Тамчы / Иссык-Куль)": "N423518 E0770220",
    "Ручной ввод": "",
}

# Latitude and longitude in aviation compact notation or DMS with separators.
LAT = r"[NSСЮnsсю]?\s*(?:\d{6}(?:[.,]\d+)?|\d{1,2}[°\s]+\d{1,2}(?:['’\s]+\d{1,2}(?:[.,]\d+)?)?)[NSСЮnsсю]?"
LON = r"[EWВЗewвз]?\s*(?:\d{7}(?:[.,]\d+)?|\d{1,3}[°\s]+\d{1,2}(?:['’\s]+\d{1,2}(?:[.,]\d+)?)?)[EWВЗewвз]?"
COORD_RE = re.compile(rf"(?<!\w)({LAT})\s+({LON})(?!\w)")
S_RE = re.compile(r"S\d+(?:[.,]\d+)?\s*(?:км|km|nm)\b", re.I)
A_RE = re.compile(r"A\d{1,3}(?:[.,]\d+)?\b", re.I)
LABEL_RE = re.compile(r"\((.*?)\)")
GEOD = Geodesic.WGS84


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float
    label: str


@dataclass(frozen=True)
class Result:
    text: str
    points: list[Point]
    warnings: list[str]
    topology: str


def parse_coordinate(value: str, is_lat: bool) -> float:
    raw = value.strip().replace(",", ".")
    hemis = re.findall(r"[NSEWСЮВЗnsewсювз]", raw)
    if len(hemis) > 1:
        raise ValueError("указано несколько обозначений полушария")
    hemi = hemis[0].upper().translate(str.maketrans({"С": "N", "Ю": "S", "В": "E", "З": "W"})) if hemis else ("N" if is_lat else "E")
    if hemi not in (("N", "S") if is_lat else ("E", "W")):
        raise ValueError("неверное полушарие")
    cleaned = re.sub(r"[NSEWСЮВЗnsewсювз°'\"’‘]", " ", raw).strip()
    pieces = cleaned.split()
    if len(pieces) in (2, 3):
        degree, minute = map(float, pieces[:2])
        second = float(pieces[2]) if len(pieces) == 3 else 0.0
    elif len(pieces) == 1:
        compact = pieces[0]
        deg_len = 2 if is_lat else 3
        # Compact DDMMSS[.sss] or DDDMMSS[.sss] only.
        if not re.fullmatch(rf"\d{{{deg_len+4}}}(?:\.\d+)?", compact):
            raise ValueError("ожидается формат DDMMSS / DDDMMSS или DMS")
        degree = float(compact[:deg_len])
        minute = float(compact[deg_len:deg_len+2])
        second = float(compact[deg_len+2:])
    else:
        raise ValueError("координата пуста или имеет неверный формат")
    limit = 90 if is_lat else 180
    if not 0 <= degree <= limit or not 0 <= minute < 60 or not 0 <= second < 60:
        raise ValueError("градусы, минуты или секунды вне допустимого диапазона")
    if degree == limit and (minute != 0 or second != 0):
        raise ValueError("превышен диапазон координаты")
    decimal = degree + minute / 60 + second / 3600
    return -decimal if hemi in ("S", "W") else decimal


def parse_point(text: str) -> tuple[float, float]:
    match = COORD_RE.search(text)
    if not match:
        raise ValueError("не найдена пара координат (например, N423101 E0721448)")
    return parse_coordinate(match[1], True), parse_coordinate(match[2], False)


def magnetic_declination(lat: float, lon: float, year: float) -> float:
    """Raise on missing model or invalid date; never silently use 0 degrees."""
    from pygeomag import GeoMag
    return GeoMag().calculate(lat, lon, 0, year).d


def bearing_text(bearing: float, decimals: bool) -> str:
    precision = 2 if decimals else 0
    rounded = round(bearing % 360, precision) % 360
    return f"A{rounded:06.2f}" if decimals else f"A{int(rounded):03d}"


def calculate(base_text: str, source: str, *, magnetic: bool = True,
              decimals: bool = False, nautical_miles: bool = False,
              clean_list: bool = False, year: float = 2026.0) -> Result:
    if not source.strip():
        return Result("", [], [], "Ожидание координат")
    base_lat, base_lon = parse_point(base_text)
    declination = magnetic_declination(base_lat, base_lon, year) if magnetic else 0.0
    output, points, warnings = [], [], []
    for index, line in enumerate(source.splitlines(), 1):
        if not line.strip():
            if not clean_list:
                output.append(line)
            continue
        match = COORD_RE.search(line)
        if not match:
            # Free-form notes are allowed in insertion mode.
            if not clean_list:
                output.append(line)
            if re.search(r"[NSEWСЮВЗnsewсювз]\s*\d", line):
                warnings.append(f"Строка {index}: координаты не распознаны")
            continue
        try:
            lat = parse_coordinate(match[1], True)
            lon = parse_coordinate(match[2], False)
        except ValueError as exc:
            warnings.append(f"Строка {index}: {exc}")
            if not clean_list:
                output.append(line)
            continue
        label_match = LABEL_RE.search(line)
        label = label_match[1] if label_match else f"Т.{len(points)+1}"
        points.append(Point(lat, lon, label))
        inverse = GEOD.Inverse(base_lat, base_lon, lat, lon)
        distance = inverse["s12"] / (1852 if nautical_miles else 1000)
        dist_text = f"S{distance:.1f}nm" if nautical_miles else f"S{distance:.1f}км".replace(".", ",")
        true_az = 0.0 if inverse["s12"] < 1e-6 else inverse["azi1"] % 360
        az_text = bearing_text(0.0 if inverse["s12"] < 1e-6 else (true_az - declination if magnetic else true_az), decimals)
        if clean_list:
            output.append(f"{match[0].strip()} {dist_text} {az_text}")
        else:
            has_distance, has_azimuth = S_RE.search(line), A_RE.search(line)
            if has_distance or has_azimuth:
                modified = S_RE.sub(lambda _: dist_text, line) if has_distance else line
                modified = A_RE.sub(lambda _: az_text, modified) if has_azimuth else modified
            else:
                modified = f"{line[:match.end()]} {dist_text} {az_text}{line[match.end():]}"
            output.append(modified)
    if len(points) >= 3:
        gap = GEOD.Inverse(points[0].lat, points[0].lon, points[-1].lat, points[-1].lon)["s12"]
        topology = f"Контур замкнут (разрыв {gap:.1f} м)" if gap < 50 else f"Контур не замкнут: разрыв {gap:.0f} м"
    else:
        topology = "Недостаточно точек для проверки замыкания"
    return Result("\n".join(output), points, warnings, topology)


def make_svg(base: tuple[float, float], points: list[Point], *, focus_boundary: bool = False) -> str:
    """Render a schematic, not a geographic navigation map."""
    if not points:
        return "<p>Добавьте координаты для построения схемы.</p>"
    # With boundary focus, fit only the actual polygon, not the possibly distant airport.
    lats = [p.lat for p in points] if focus_boundary else [base[0], *[p.lat for p in points]]
    lons = [p.lon for p in points] if focus_boundary else [base[1], *[p.lon for p in points]]
    min_lat, min_lon = min(lats), min(lons)
    dy = max(max(lats)-min_lat, 1e-9)
    factor = max(abs(math.cos(math.radians((min(lats)+max(lats))/2))), 1e-6)
    dx = max((max(lons)-min_lon)*factor, 1e-9)
    width, height, padding = 800, 500, 45
    scale = min((width-2*padding)/dx, (height-2*padding)/dy)
    def pos(lat: float, lon: float) -> tuple[float, float]:
        return ((width-dx*scale)/2 + (lon-min_lon)*factor*scale,
                (height+dy*scale)/2 - (lat-min_lat)*scale)
    coords = [pos(p.lat, p.lon) for p in points]
    polyline = " ".join(f"{x:.2f},{y:.2f}" for x,y in coords)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" style="width:100%;background:#fff;border-radius:8px">',
             f'<polyline points="{polyline}" stroke="#1685a8" stroke-width="2.5" fill="none"/>']
    for point, (x,y) in zip(points, coords):
        parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" fill="#1685a8"/>')
        parts.append(f'<text x="{x+8:.2f}" y="{y-8:.2f}" font-size="13" fill="#222">{html.escape(point.label)}</text>')
    x,y = pos(*base)
    # Do not draw a faraway airport outside the visible boundary-only viewport.
    if not focus_boundary or (0 <= x <= width and 0 <= y <= height):
        parts.append(f'<polygon points="{x:.2f},{y-8:.2f} {x-8:.2f},{y+6:.2f} {x+8:.2f},{y+6:.2f}" fill="#d32f2f"/>')
        parts.append(f'<text x="{x+10:.2f}" y="{y-3:.2f}" font-size="14" fill="#d32f2f">КТА</text>')
    return "".join(parts) + "</svg>"
