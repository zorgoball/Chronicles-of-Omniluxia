#!/usr/bin/env python3
"""Generate first-pass map object locators for new_world_region provinces.

This fills locator categories that are completely absent for the second
continent by reusing the existing vfx locator as an anchor. Type-specific
offsets are snapped back into the province color on provinces.png, so the
generated locators remain inside their province whenever the bitmap agrees
with definition.csv.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path

from PIL import Image

from audit_second_continent import (
    LOCATOR_FILES,
    MAP_DATA,
    NEW_WORLD_REGION,
    NEW_WORLD_SETUP,
    ROOT,
    parse_locator_ids,
    parse_setup,
)


TARGET_LOCATORS = ("city", "fort", "great_work", "unit_stack", "combat")

# Map-space offsets from the vfx anchor. Pixel-space Y is inverted later.
OFFSETS = {
    "city": (0.0, 0.0),
    "fort": (6.0, 4.0),
    "great_work": (-6.0, 4.0),
    "unit_stack": (0.0, 0.0),
    "combat": (0.0, -3.0),
}

SNAP_RADII = (0, 2, 4, 8, 16, 32, 64, 96, 128, 192)


def parse_definition_colors(path: Path) -> dict[int, tuple[int, int, int]]:
    colors: dict[int, tuple[int, int, int]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle, delimiter=";"):
            if row and row[0].isdigit():
                colors[int(row[0])] = (int(row[1]), int(row[2]), int(row[3]))
    return colors


def parse_locator_positions(path: Path) -> dict[int, tuple[float, float]]:
    text = path.read_text(encoding="utf-8-sig")
    positions: dict[int, tuple[float, float]] = {}
    pattern = re.compile(
        r"\bid\s*=\s*(\d+)\s+position\s*=\s*\{\s*([-0-9.]+)\s+[-0-9.]+\s+([-0-9.]+)",
        re.S,
    )
    for match in pattern.finditer(text):
        positions[int(match.group(1))] = (float(match.group(2)), float(match.group(3)))
    return positions


def map_to_pixel(x: float, z: float, height: int) -> tuple[int, int]:
    return int(round(x)), int(round(height - 1 - z))


def pixel_to_map(px: int, py: int, height: int) -> tuple[float, float]:
    return float(px), float(height - 1 - py)


def snap_to_province(
    pixels,
    width: int,
    height: int,
    color: tuple[int, int, int],
    target_x: float,
    target_z: float,
    fallback_x: float,
    fallback_z: float,
) -> tuple[float, float]:
    target_px, target_py = map_to_pixel(target_x, target_z, height)
    fallback_px, fallback_py = map_to_pixel(fallback_x, fallback_z, height)

    def matches(px: int, py: int) -> bool:
        return 0 <= px < width and 0 <= py < height and pixels[px, py] == color

    if matches(target_px, target_py):
        return pixel_to_map(target_px, target_py, height)

    for radius in SNAP_RADII[1:]:
        best: tuple[int, int] | None = None
        best_dist = float("inf")
        min_x = max(0, target_px - radius)
        max_x = min(width - 1, target_px + radius)
        min_y = max(0, target_py - radius)
        max_y = min(height - 1, target_py + radius)
        for py in range(min_y, max_y + 1):
            for px in range(min_x, max_x + 1):
                if not matches(px, py):
                    continue
                dist = (px - target_px) ** 2 + (py - target_py) ** 2
                if dist < best_dist:
                    best = (px, py)
                    best_dist = dist
        if best is not None:
            return pixel_to_map(best[0], best[1], height)

    if matches(fallback_px, fallback_py):
        return pixel_to_map(fallback_px, fallback_py, height)

    return fallback_x, fallback_z


def rotation_for(locator_name: str, province_id: int) -> tuple[float, float, float, float]:
    if locator_name in {"unit_stack", "combat"}:
        return (-0.0, -0.0, -0.0, 1.0)
    # Deterministic pseudo-random Y-axis rotation, matching the file shape.
    angle = ((province_id * 137.508) % 360.0) * math.pi / 180.0
    return (-0.0, math.sin(angle / 2.0), -0.0, math.cos(angle / 2.0))


def format_instance(locator_name: str, province_id: int, x: float, z: float) -> str:
    rx, ry, rz, rw = rotation_for(locator_name, province_id)
    return (
        "\t\t{\n"
        f"\t\t\tid={province_id}\n"
        f"\t\t\tposition={{ {x:.6f} 0.000000 {z:.6f} }}\n"
        f"\t\t\trotation={{ {rx:.6f} {ry:.6f} {rz:.6f} {rw:.6f} }}\n"
        "\t\t\tscale={ 1.000000 1.000000 1.000000 }\n"
        "\t\t}\n"
    )


def append_instances(path: Path, instances: list[str]) -> None:
    text = path.read_text(encoding="utf-8-sig")
    marker = "\n\t}\n}"
    index = text.rfind(marker)
    if index == -1:
        raise ValueError(f"Could not find locator footer in {path}")
    new_text = text[:index] + "\n" + "".join(instances) + text[index:]
    path.write_text(new_text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=NEW_WORLD_REGION)
    parser.add_argument("--setup", type=Path, default=NEW_WORLD_SETUP)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write generated instances. Omit for a dry run.",
    )
    args = parser.parse_args()

    setup_path = args.setup if args.setup.is_absolute() else ROOT / args.setup
    setup_ids, _, _ = parse_setup(setup_path.resolve())

    vfx_positions = parse_locator_positions(LOCATOR_FILES["vfx"])
    missing_vfx = setup_ids - set(vfx_positions)
    if missing_vfx:
        sample = " ".join(map(str, sorted(missing_vfx)[:20]))
        raise SystemExit(f"Cannot generate without vfx anchors for: {sample}")

    colors = parse_definition_colors(MAP_DATA / "definition.csv")
    image = Image.open(MAP_DATA / "provinces.png").convert("RGB")
    width, height = image.size
    pixels = image.load()

    print(f"Setup provinces: {len(setup_ids)}")
    print(f"Mode: {'apply' if args.apply else 'dry-run'}")

    for locator_name in TARGET_LOCATORS:
        path = LOCATOR_FILES[locator_name]
        existing_ids = parse_locator_ids(path)
        missing_ids = sorted(setup_ids - existing_ids)
        print(f"{locator_name}: {len(missing_ids)} missing")
        if not missing_ids:
            continue

        dx, dz = OFFSETS[locator_name]
        instances: list[str] = []
        for province_id in missing_ids:
            anchor_x, anchor_z = vfx_positions[province_id]
            color = colors[province_id]
            x, z = snap_to_province(
                pixels,
                width,
                height,
                color,
                anchor_x + dx,
                anchor_z + dz,
                anchor_x,
                anchor_z,
            )
            instances.append(format_instance(locator_name, province_id, x, z))

        if args.apply:
            append_instances(path, instances)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
