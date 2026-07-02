#!/usr/bin/env python3
"""Generate first-pass ports for new_world_region coastal provinces."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from audit_second_continent import (
    LOCATOR_FILES,
    MAP_DATA,
    NEW_WORLD_SETUP,
    ROOT,
    parse_default_lists,
    parse_locator_ids,
    parse_ports,
    parse_setup,
)
from generate_new_world_locators import format_instance, parse_definition_colors


PORTS_CSV = MAP_DATA / "ports.csv"


def append_port_rows(rows: list[str]) -> None:
    data = PORTS_CSV.read_bytes()
    marker = b"end;end;-1;-1;"
    index = data.rfind(marker)
    if index == -1:
        raise ValueError("Could not find ports.csv sentinel")
    row_bytes = b"".join(row.rstrip("\r\n").encode("utf-8") + b"\n" for row in rows)
    PORTS_CSV.write_bytes(data[:index] + row_bytes + data[index:])


def append_port_locators(instances: list[str]) -> None:
    path = LOCATOR_FILES["port"]
    text = path.read_text(encoding="utf-8-sig")
    marker = "\n\t}\n}"
    index = text.rfind(marker)
    if index == -1:
        raise ValueError("Could not find port locator footer")
    path.write_text(text[:index] + "\n" + "".join(instances) + text[index:], encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", type=Path, default=NEW_WORLD_SETUP)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    setup_path = args.setup if args.setup.is_absolute() else ROOT / args.setup
    setup_ids, setup_fields, _ = parse_setup(setup_path.resolve())
    coastal_ids = {
        pid
        for pid, fields in setup_fields.items()
        if fields.get("terrain") == "coastal_terrain"
    }
    existing_ports = parse_ports(PORTS_CSV)
    missing_ports = coastal_ids - existing_ports
    sea_ids = parse_default_lists(MAP_DATA / "default.map")["sea_zones"]

    colors = parse_definition_colors(MAP_DATA / "definition.csv")
    color_to_id = {colors[pid]: pid for pid in (missing_ports | sea_ids) if pid in colors}

    image = Image.open(MAP_DATA / "provinces.png").convert("RGB")
    width, height = image.size
    contacts: dict[int, Counter[int]] = {pid: Counter() for pid in missing_ports}
    sums: dict[tuple[int, int], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])

    for y in range(height):
        row_image = image.crop((0, y, width, y + 1))
        row = row_image.get_flattened_data() if hasattr(row_image, "get_flattened_data") else row_image.getdata()
        next_row = None
        if y + 1 < height:
            next_image = image.crop((0, y + 1, width, y + 2))
            next_row = next_image.get_flattened_data() if hasattr(next_image, "get_flattened_data") else next_image.getdata()
        for x in range(width):
            current = color_to_id.get(row[x])
            if current is None:
                continue
            neighbors: list[tuple[int, int, int]] = []
            if x + 1 < width:
                right = color_to_id.get(row[x + 1])
                if right is not None:
                    neighbors.append((right, x + 0.5, y))
            if next_row is not None:
                down = color_to_id.get(next_row[x])
                if down is not None:
                    neighbors.append((down, x, y + 0.5))
            for neighbor, bx, by in neighbors:
                if current in missing_ports and neighbor in sea_ids:
                    land, sea = current, neighbor
                elif neighbor in missing_ports and current in sea_ids:
                    land, sea = neighbor, current
                else:
                    continue
                contacts[land].update([sea])
                sums[(land, sea)][0] += bx
                sums[(land, sea)][1] += by
                sums[(land, sea)][2] += 1

    generated: list[tuple[int, int, float, float]] = []
    skipped: list[int] = []
    for land in sorted(missing_ports):
        if not contacts[land]:
            skipped.append(land)
            continue
        sea, _ = contacts[land].most_common(1)[0]
        sx, sy, count = sums[(land, sea)]
        x = sx / count
        z = height - 1 - (sy / count)
        generated.append((land, sea, x, z))

    print(f"Coastal setup provinces: {len(coastal_ids)}")
    print(f"Existing ports on them: {len(coastal_ids & existing_ports)}")
    print(f"Ports to generate: {len(generated)}")
    print(f"Skipped coastal provinces without sea contact: {len(skipped)}")
    if skipped:
        print("  " + " ".join(map(str, skipped[:20])))
    print(f"Mode: {'apply' if args.apply else 'dry-run'}")

    existing_locator_ids = parse_locator_ids(LOCATOR_FILES["port"])
    locator_instances = [
        format_instance("port", land, x, z)
        for land, _sea, x, z in generated
        if land not in existing_locator_ids
    ]
    rows = [f"{land};{sea};{x:.3f};{z:.3f};\n" for land, sea, x, z in generated]

    if args.apply and generated:
        append_port_rows(rows)
        if locator_instances:
            append_port_locators(locator_instances)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
