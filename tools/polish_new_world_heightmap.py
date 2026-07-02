#!/usr/bin/env python3
"""Polish pass for the New World heightmap.

Fixes the generated-terrain artifacts visible in hillshade renders:

1. De-terrace: gaussian smoothing removes the quantized "contour ring"
   stair-steps that cover the generated relief.
2. Mid-scale relief: adds gentle multi-octave noise (amplitude scaled by
   elevation) so the east matches the western continent's roughness instead
   of reading as smooth plastic.
3. River burn: lowers terrain slightly under and beside river pixels so the
   copied western rivers sit in shallow valleys instead of climbing ridges.
4. Protection: coastlines (blend ramp), lake basins (kept below waterline),
   and sea floor are preserved.

Run repack_packed_heightmap.py --apply afterwards or the game won't see it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parents[1]
MAP_DATA = ROOT / "map_data"

# New World bounding box (from audit_new_world_map_layers.py, +margin)
X0, X1, Y0, Y1 = 5840, 8134, 368, 3866
WATERLINE = 39
LAKE_IDS = (471, 581, 1103, 1204, 2453, 2835, 4851, 5408)

SMOOTH_SIGMA = 1.6
NOISE_OCTAVES = ((28.0, 3.2), (12.0, 2.2), (5.0, 1.6), (2.2, 1.1))  # (sigma, amplitude)
RIVER_DEPTH = 3.5
RIVER_FALLOFF = 1.2
COAST_RAMP_PX = 8


def lake_mask(shape: tuple[int, int]) -> np.ndarray:
    import csv

    colors = {}
    with open(MAP_DATA / "definition.csv", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle, delimiter=";"):
            if row and row[0].isdigit() and int(row[0]) in LAKE_IDS:
                colors[int(row[0])] = (int(row[1]), int(row[2]), int(row[3]))
    prov = np.array(Image.open(MAP_DATA / "provinces.png").convert("RGB"))[Y0:Y1, X0:X1]
    mask = np.zeros(shape, dtype=bool)
    for rgb in colors.values():
        mask |= (prov[:, :, 0] == rgb[0]) & (prov[:, :, 1] == rgb[1]) & (prov[:, :, 2] == rgb[2])
    return mask


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes. Omit for a dry run.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    hm_img = Image.open(MAP_DATA / "heightmap.png").convert("L")
    hm = np.array(hm_img, dtype=np.float32)
    sub = hm[Y0:Y1, X0:X1].copy()
    original = sub.copy()

    land = sub >= WATERLINE
    lakes = lake_mask(sub.shape)

    # Coast protection ramp: 0 at the waterline, 1 inland.
    d_land = ndimage.distance_transform_edt(land)
    ramp = np.clip(d_land / COAST_RAMP_PX, 0.0, 1.0).astype(np.float32)

    # 1. De-terrace.
    smooth = ndimage.gaussian_filter(sub, sigma=SMOOTH_SIGMA)
    sub = np.where(land, sub + (smooth - sub) * ramp, sub)

    # 2. Mid-scale relief noise, elevation-scaled, land only, away from coast.
    rng = np.random.default_rng(args.seed)
    noise = np.zeros_like(sub)
    for sigma, amp in NOISE_OCTAVES:
        field = ndimage.gaussian_filter(rng.standard_normal(sub.shape).astype(np.float32), sigma)
        field /= max(field.std(), 1e-6)
        noise += field * amp
    elev_scale = np.clip((sub - WATERLINE) / 70.0, 0.45, 1.0)
    sub = np.where(land & ~lakes, sub + noise * elev_scale * ramp, sub)

    # 3. River burn: shallow valleys under river pixels.
    riv = np.array(Image.open(MAP_DATA / "rivers.png").convert("P"))[Y0:Y1, X0:X1]
    river = riv < 16
    if river.any():
        d_riv = ndimage.distance_transform_edt(~river)
        burn = np.clip(RIVER_DEPTH - RIVER_FALLOFF * d_riv, 0.0, None).astype(np.float32)
        burned = sub - burn
        # rivers stay on land: don't burn below waterline+1
        burned = np.maximum(burned, WATERLINE + 1)
        apply_burn = land & ~lakes & (burn > 0)
        sub = np.where(apply_burn, np.minimum(sub, burned), sub)

    # 4. Re-assert lake basins below the waterline.
    sub[lakes] = np.minimum(sub[lakes], WATERLINE - 2)
    # Never let former land drop below the waterline (except lakes).
    sub = np.where(land & ~lakes, np.maximum(sub, WATERLINE + 1), sub)

    out = np.clip(np.rint(sub), 0, 255).astype(np.uint8)
    changed = int((out != original.astype(np.uint8)).sum())
    diff = np.abs(sub - original)
    print(f"changed pixels: {changed}  mean abs delta (land): {diff[land].mean():.2f}  max: {diff.max():.1f}")

    gy, gx = np.gradient(sub)
    rough = np.hypot(gx, gy)[land]
    print(f"east land roughness now: mean={rough.mean():.2f} std={rough.std():.2f} (west ref ~2.7/3.8)")

    if args.apply:
        full = np.array(hm_img, dtype=np.uint8)
        full[Y0:Y1, X0:X1] = out
        Image.fromarray(full, mode="L").save(MAP_DATA / "heightmap.png")
        print("heightmap.png written — now run repack_packed_heightmap.py --apply")
    else:
        print("Dry run only. Re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
