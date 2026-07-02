#!/usr/bin/env python3
"""Verify the eastern continent's area/region density and food self-sufficiency.

Read-only. Cross-checks map_data/areas.txt, map_data/regions.txt,
localization/english/regionnames_l_english.yml, and
setup/provinces/00_new_world_region.txt against each other, and reports
stats for comparison against the west continent's density.
"""
from __future__ import annotations

import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] if (Path(__file__).resolve().parents[1] / "map_data").exists() else Path(".")

FOOD_GOODS = {"grain", "fish", "cattle", "vegetables", "fruits", "honey", "dates"}


def parse_blocks(text: str, prefix: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r"(?m)^(" + prefix + r"[a-zA-Z0-9_]*)\s*=\s*\{", text):
        name = m.group(1)
        start = m.end()
        depth = 1
        i = start
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        out[name] = text[start:i - 1]
    return out


def main() -> None:
    areas_text = (ROOT / "map_data/areas.txt").read_text(encoding="utf-8-sig")
    regions_text = (ROOT / "map_data/regions.txt").read_text(encoding="utf-8-sig")
    loc_text = (ROOT / "localization/english/regionnames_l_english.yml").read_text(encoding="utf-8-sig")
    setup_text = (ROOT / "setup/provinces/00_new_world_region.txt").read_text(encoding="utf-8-sig")

    area_blocks = parse_blocks(areas_text, "new_world_")
    areas = {k: [int(x) for x in re.findall(r"\d+", v)] for k, v in area_blocks.items()}

    region_blocks = parse_blocks(regions_text, "new_world_")
    region_blocks.pop("new_world_seas", None)
    regions = {k: re.findall(r"new_world_[a-zA-Z0-9_]+", v) for k, v in region_blocks.items()}

    print(f"Areas: {len(areas)}   Regions: {len(regions)}")

    all_ids = [i for v in areas.values() for i in v]
    print(f"Territories covered: {len(all_ids)} (unique: {len(set(all_ids))})")

    sizes = [len(v) for v in areas.values()]
    print(
        f"Territories/area  min={min(sizes)} max={max(sizes)} "
        f"avg={sum(sizes)/len(sizes):.2f} median={statistics.median(sizes)}"
    )

    area_refs = [a for v in regions.values() for a in v]
    print(f"Areas/region covered: {len(area_refs)} (unique: {len(set(area_refs))})")
    rsizes = [len(v) for v in regions.values()]
    print(
        f"Areas/region       min={min(rsizes)} max={max(rsizes)} "
        f"avg={sum(rsizes)/len(rsizes):.2f} median={statistics.median(rsizes)}"
    )

    loc_keys = set(re.findall(r"(?m)^\s*(new_world_[a-zA-Z0-9_]+):0", loc_text))
    missing_loc = (set(areas) | set(regions)) - loc_keys
    print(f"Missing localization: {sorted(missing_loc) if missing_loc else 'none'}")

    blocks = re.findall(r"(?m)^(\d+)=\{(.*?)\n\}", setup_text, re.DOTALL)
    trade_goods = {}
    rank = {}
    for pid, body in blocks:
        pid = int(pid)
        m = re.search(r'trade_goods="([a-z_]+)"', body)
        if m:
            trade_goods[pid] = m.group(1)
        m2 = re.search(r'province_rank="([a-z_]+)"', body)
        if m2:
            rank[pid] = m2.group(1)

    no_food = [a for a, ids in areas.items() if not any(trade_goods.get(i) in FOOD_GOODS for i in ids)]
    print(f"Areas with no food-producing territory: {len(no_food)} {no_food}")

    city_count = sum(1 for r in rank.values() if r == "city")
    print(f"province_rank='city' total: {city_count}")


if __name__ == "__main__":
    main()
