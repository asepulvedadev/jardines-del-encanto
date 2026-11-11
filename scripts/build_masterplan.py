#!/usr/bin/env python3
"""Extract source CAD parcels, printed identifiers, areas and edge labels.

Usage: python scripts/build_masterplan.py path/to/source.pdf
Dependencies: scripts/masterplan_requirements.txt. Never infer availability.
"""

from __future__ import annotations
import argparse, collections, hashlib, html, json, math, os, re, tempfile
from pathlib import Path
import pdfplumber
from shapely import unary_union
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points, polygonize
from shapely.strtree import STRtree

SOURCE_HASH = "e80b746e47b808f077432a61a6794993205a244e896667b2e16d51feb416f74d"
ROOT = Path(__file__).resolve().parents[1]
FOLIAGE = {
    (0.0, 1.0, 0.0),
    (0.18039, 0.72157, 0.0),
    (0.07451, 0.40392, 0.20392),
    (0.74902, 1.0, 0.49804),
}


def fmt(v):
    return f"{v:.3f}".rstrip("0").rstrip(".")


def svg_path(poly):
    def ring(coords):
        pts = list(coords)
        return "M" + "L".join(f"{fmt(x)} {fmt(y)}" for x, y in pts) + "Z"

    if poly.geom_type == "MultiPolygon":
        return "".join(svg_path(p) for p in poly.geoms)
    return ring(poly.exterior.coords) + "".join(ring(r.coords) for r in poly.interiors)


def text_runs(chars):
    runs = []
    for c in chars:
        same = False
        if runs:
            p = runs[-1][-1]
            a, b, *_ = c["matrix"]
            pa, pb, *_ = p["matrix"]
            ex, ey = c["matrix"][4:]
            sx, sy = p["matrix"][4:]
            same = (
                c["non_stroking_color"] == p["non_stroking_color"]
                and c["fontname"] == p["fontname"]
                and abs(a - pa) < 0.00001
                and abs(b - pb) < 0.00001
                and math.hypot(ex - sx - pa * p["adv"], ey - sy - pb * p["adv"]) < 1
            )
        if same:
            runs[-1].append(c)
        else:
            runs.append([c])
    return [
        dict(
            text="".join(c["text"] for c in r),
            x=sum((c["x0"] + c["x1"]) / 2 for c in r) / len(r),
            y=sum((c["top"] + c["bottom"]) / 2 for c in r) / len(r),
            angle=math.atan2(r[0]["matrix"][1], r[0]["matrix"][0]),
        )
        for r in runs
    ]


def flatten_cubic(p0, p1, p2, p3, depth=0):
    """Bound control-point deviation to 0.005 PDF points, retaining source curvature."""
    chord = LineString([p0, p3])
    if (
        depth >= 18
        or max(chord.distance(Point(p1)), chord.distance(Point(p2))) <= 0.005
    ):
        return [p0, p3]
    mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    a = mid(p0, p1)
    b = mid(p1, p2)
    c = mid(p2, p3)
    d = mid(a, b)
    e = mid(b, c)
    f = mid(d, e)
    return flatten_cubic(p0, a, d, f, depth + 1)[:-1] + flatten_cubic(
        f, e, c, p3, depth + 1
    )


def source_segments(objects):
    segments = []
    for typ in ["curve", "line", "rect"]:
        for obj in objects[typ]:
            if (
                obj.get("stroking_color") in FOLIAGE
                or obj.get("stroking_color") is None
            ):
                continue
            start = cur = None
            for cmd in obj.get("path", []):
                if cmd[0] == "m":
                    start = cur = cmd[1]
                elif cmd[0] == "l":
                    if cur != cmd[1]:
                        segments.append(LineString([cur, cmd[1]]))
                    cur = cmd[1]
                elif cmd[0] == "c":
                    p0 = cur
                    p1, p2, p3 = cmd[1:]
                    points = flatten_cubic(p0, p1, p2, p3)
                    segments.extend(
                        LineString([a, b]) for a, b in zip(points, points[1:]) if a != b
                    )
                    cur = p3
                elif cmd[0] == "h":
                    if cur is not None and start != cur:
                        segments.append(LineString([cur, start]))
                    cur = start
    return segments


def reconcile_endpoints(segments):
    """Repair <=0.2pt quantization gaps against existing nonparallel source edges."""
    tree = STRtree(segments)
    result = []
    count = 0
    for line in segments:
        ends = list(line.coords)
        dx = ends[1][0] - ends[0][0]
        dy = ends[1][1] - ends[0][1]
        for j, xy in enumerate(ends):
            point = Point(xy)
            candidates = []
            for k in tree.query(point.buffer(0.2)):
                target = segments[k]
                a, b = list(target.coords)
                tx = b[0] - a[0]
                ty = b[1] - a[1]
                if (
                    abs(dx * ty - dy * tx) / max(line.length * target.length, 0.00001)
                    < 0.05
                ):
                    continue
                distance = point.distance(target)
                if distance <= 0.2:
                    candidates.append((distance, target))
            if candidates:
                distance, target = min(candidates, key=lambda x: x[0])
                if distance > 0.00001:
                    ends[j] = tuple(nearest_points(point, target)[1].coords)[0]
                    count += 1
        result.append(LineString(ends))
    return result, count


def source_contact_faces(objects, original, reconciled):
    """Recover missing faces without discarding source vertices or inventing dividers.

    Legacy endpoint projection can move two coincident source edges independently.
    Preserve both original and projected edges. Tangential CAD joins also have tiny
    independently quantized command endpoints: link only same-color stroke contacts
    <=0.2pt, and only inside both actual printed stroke widths. Never link sampled
    cubic subdivision points, which are not source command endpoints.
    """
    endpoints = {}
    for typ in ["curve", "line", "rect"]:
        for obj in objects[typ]:
            color = obj.get("stroking_color")
            width = obj.get("linewidth", 0)
            if color in FOLIAGE or color is None or not obj.get("stroke") or width <= 0:
                continue
            for command in obj.get("path", []):
                if command[0] in {"m", "l", "c"}:
                    endpoint = command[-1]
                    styles = endpoints.setdefault(endpoint, {})
                    styles[color] = max(styles.get(color, 0), width)
    coordinates = sorted(endpoints)
    points = [Point(xy) for xy in coordinates]
    tree = STRtree(points)
    contacts = []
    for i, point in enumerate(points):
        for j in tree.query(point.buffer(0.2)):
            if j <= i:
                continue
            distance = point.distance(points[j])
            shared = endpoints[coordinates[i]].keys() & endpoints[coordinates[j]].keys()
            if not 0.001 < distance <= 0.2 or not shared:
                continue
            overlap = max(
                (endpoints[coordinates[i]][color] + endpoints[coordinates[j]][color])
                / 2
                for color in shared
            )
            if distance <= overlap:
                contacts.append(LineString([point, points[j]]))
    faces = [
        polygon
        for polygon in polygonize(
            unary_union(original + reconciled + contacts, grid_size=0.001)
        )
        if polygon.area > 20
    ]
    return faces, len(contacts)


def extract(objects, geometry_cache=None):
    labels = text_runs(objects["char"])
    lots = [x for x in labels if x["text"].startswith("LT")]
    if len(lots) != 1568:
        raise ValueError("Source label count differs from audited 1,568 occurrences")
    areas = [l for l in labels if re.fullmatch(r"A:\s*[\d.]+(?:\s*m²)?", l["text"])]
    unit_areas = sum(l["text"].endswith("m²") for l in areas)
    dimensions = [l for l in labels if re.fullmatch(r"\d+\.\d+", l["text"])]
    if geometry_cache is None:
        original = source_segments(objects)
        segments, repair_count = reconcile_endpoints(original)
        faces = [
            p for p in polygonize(unary_union(segments, grid_size=0.001)) if p.area > 20
        ]
    else:
        faces, repair_count = geometry_cache
    area_points = [Point(a["x"], a["y"]) for a in areas]
    area_tree = STRtree(area_points)
    dim_points = [Point(d["x"], d["y"]) for d in dimensions]
    dim_tree = STRtree(dim_points)
    lot_tree = STRtree([Point(l["x"], l["y"]) for l in lots])
    tree = STRtree(faces)
    matches = []
    for label in lots:
        point = Point(label["x"], label["y"])
        hits = [int(i) for i in tree.query(point) if faces[i].covers(point)]
        matches.append(min(hits, key=lambda i: faces[i].area) if hits else None)
    face_counts = collections.Counter(i for i in matches if i is not None)
    contact_indices = set()
    contact_count = 0
    unresolved = [
        i for i, match in enumerate(matches) if match is None or face_counts[match] != 1
    ]
    if unresolved and geometry_cache is None:
        supplemental, contact_count = source_contact_faces(objects, original, segments)
        supplemental_tree = STRtree(supplemental)
        for i in unresolved:
            point = Point(lots[i]["x"], lots[i]["y"])
            candidates = [
                supplemental[j]
                for j in supplemental_tree.query(point)
                if supplemental[j].covers(point)
                and sum(
                    supplemental[j].covers(Point(lots[k]["x"], lots[k]["y"]))
                    for k in lot_tree.query(supplemental[j])
                )
                == 1
            ]
            if candidates:
                # Existing 1,564 audited paths remain byte-identical. Only a face
                # previously rejected as missing/merged can use contact recovery.
                matches[i] = len(faces)
                faces.append(min(candidates, key=lambda polygon: polygon.area))
                contact_indices.add(i)
        face_counts = collections.Counter(i for i in matches if i is not None)
    label_counts = collections.Counter(l["text"] for l in lots)
    parsed = [re.fullmatch(r"LT\s*(\d+[a-z]?)-(\d+[a-z]?)", l["text"]) for l in lots]
    result = []
    for index, (label, match) in enumerate(zip(lots, matches)):
        anomalies = []
        name = parsed[index]
        if name:
            block = name[1]
        else:
            # Spatial group association is not a correction of the printed identifier.
            nearby = min(
                (j for j, p in enumerate(parsed) if p),
                key=lambda j: math.hypot(
                    lots[j]["x"] - label["x"], lots[j]["y"] - label["y"]
                ),
            )
            block = parsed[nearby][1]
            anomalies.extend(["malformed-source-label", "spatial-block-association"])
        if label_counts[label["text"]] > 1:
            anomalies.append("duplicate-source-label")
        poly = faces[match] if match is not None and face_counts[match] == 1 else None
        if poly is None:
            anomalies.append("unresolved-source-boundary")
        point = Point(label["x"], label["y"])
        contained = (
            [areas[i] for i in area_tree.query(poly) if poly.covers(area_points[i])]
            if poly is not None
            else []
        )
        area = (
            min(contained, key=lambda a: point.distance(Point(a["x"], a["y"])))
            if contained
            else areas[area_tree.nearest(point)]
        )
        if point.distance(Point(area["x"], area["y"])) > 25 or (
            not contained
            and int(lot_tree.nearest(Point(area["x"], area["y"]))) != index
        ):
            area = None
        if len(contained) > 1:
            anomalies.append("multiple-source-area-labels")
        has_area_unit = area is not None and area["text"].endswith("m²")
        if area is not None and not has_area_unit:
            anomalies.append("source-area-unit-missing")
        measurements = []
        if poly is not None:
            coords = list(poly.exterior.coords)
            edges = [LineString([a, b]) for a, b in zip(coords, coords[1:])]
            for dim_index in dim_tree.query(poly.buffer(5.5)):
                dim = dimensions[dim_index]
                dp = dim_points[dim_index]
                if poly.boundary.distance(dp) > 5.5:
                    continue
                edge_index = min(range(len(edges)), key=lambda i: edges[i].distance(dp))
                edge = edges[edge_index]
                a, b = list(edge.coords)
                angle = math.atan2(-(b[1] - a[1]), b[0] - a[0])
                delta = abs(math.sin(angle - dim["angle"]))
                # Keep dimension text near a parallel edge; never derive metres from page coordinates.
                if delta > 0.18:
                    continue
                measurements.append(
                    dict(
                        value=dim["text"],
                        source="printed-pdf-edge-label",
                        position=[round(dim["x"], 3), round(dim["y"], 3)],
                        edgeIndex=edge_index,
                    )
                )
        result.append(
            dict(
                id=f"source-lot-{index + 1:04d}",
                sourceLabel=label["text"],
                blockId=block,
                areaM2=float(re.search(r"[\d.]+", area["text"])[0])
                if has_area_unit
                else None,
                areaSource=(
                    "printed-pdf-label"
                    if has_area_unit
                    else "printed-pdf-label-without-unit"
                )
                if area
                else None,
                areaLabel=area["text"] if area else None,
                areaPosition=[round(area["x"], 3), round(area["y"], 3)]
                if area
                else None,
                measurements=measurements,
                path=svg_path(poly) if poly is not None else None,
                bounds=[round(v, 3) for v in poly.bounds]
                if poly is not None
                else [
                    round(label["x"] - 2, 3),
                    round(label["y"] - 2, 3),
                    round(label["x"] + 2, 3),
                    round(label["y"] + 2, 3),
                ],
                center=[round(label["x"], 3), round(label["y"], 3)],
                geometrySource=(
                    "source-vector-stroke-contact-reconciled"
                    if index in contact_indices
                    else "source-vector-endpoint-reconciled"
                )
                if poly is not None
                else "unresolved",
                anomalies=anomalies,
            )
        )
    blocks = []
    for block in sorted(
        {l["blockId"] for l in result}, key=lambda b: (int(re.search(r"\d+", b)[0]), b)
    ):
        members = [l for l in result if l["blockId"] == block]
        bounds = [
            min(l["bounds"][0] for l in members),
            min(l["bounds"][1] for l in members),
            max(l["bounds"][2] for l in members),
            max(l["bounds"][3] for l in members),
        ]
        blocks.append(
            dict(
                id=block,
                label=f"Manzana {block}",
                count=len(members),
                bounds=bounds,
                path="".join(l["path"] or "" for l in members),
            )
        )
    bounds = [
        min(b["bounds"][0] for b in blocks) - 30,
        min(b["bounds"][1] for b in blocks) - 30,
        max(b["bounds"][2] for b in blocks) + 30,
        max(b["bounds"][3] for b in blocks) + 30,
    ]
    unresolved = sum(l["path"] is None for l in result)
    data = dict(
        metadata=dict(
            sourceSha256=SOURCE_HASH,
            sourceLabelOccurrences=len(lots),
            sourceAreaLabels=sum(l["text"].startswith("A:") for l in labels),
            parseableAreaLabels=unit_areas,
            resolvedGeometry=len(lots) - unresolved,
            unresolvedGeometry=unresolved,
            georeferenced=False,
            endpointReconciliations=repair_count,
            sourceStrokeContacts=contact_count,
            contactRecoveredGeometry=len(contact_indices),
            extraction="PDF vectors; adaptive cubic flattening <=0.005 pt; existing-edge endpoint reconciliation <=0.2 pt; source-vertex-preserving stroke contacts <=0.2 pt for unresolved faces; no raster tracing",
        ),
        viewBox=[bounds[0], bounds[1], bounds[2] - bounds[0], bounds[3] - bounds[1]],
        blocks=blocks,
        lots=result,
    )
    return data


def context_svg(objects):
    # Only source road surfaces: no embedded raster, foliage CAD noise, branding or poster text.
    paths = []
    for obj in objects["curve"]:
        if obj.get("stroking_color") not in {
            (0.46275, 0.46275, 0.46275),
            (0.85882, 0.85882, 0.85882),
        }:
            continue
        if (
            obj["x0"] < 100
            or obj["x1"] > 2660
            or obj["top"] < 430
            or obj["bottom"] > 3420
        ):
            continue
        commands = []
        for cmd in obj["path"]:
            commands.append(
                cmd[0].upper()
                + (
                    " ".join(f"{fmt(x)} {fmt(y)}" for x, y in cmd[1:])
                    if len(cmd) > 1
                    else ""
                )
            )
        paths.append('<path d="' + "".join(commands) + '"/>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2835 4008"><g fill="#dfe5d8" stroke="none">'
        + "".join(paths)
        + "</g></svg>"
    )


def atomic_write(path, content):
    """Do not expose partially generated JSON/SVG to a running development server."""
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(content)
    try:
        temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    if hashlib.sha256(args.pdf.read_bytes()).hexdigest() != SOURCE_HASH:
        raise ValueError(
            "Unexpected PDF hash; source must be audited before regeneration"
        )
    with pdfplumber.open(args.pdf) as pdf:
        objects = pdf.pages[0].objects
    data = extract(objects)
    atomic_write(
        ROOT / "apps/web/lib/masterplan-data.json",
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
    )
    atomic_write(
        ROOT / "apps/web/public/media/masterplan-context.svg",
        context_svg(objects) + "\n",
    )
    print(json.dumps(data["metadata"], indent=2))
    print("Unresolved:", [l["sourceLabel"] for l in data["lots"] if l["path"] is None])


if __name__ == "__main__":
    main()
