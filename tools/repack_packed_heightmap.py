#!/usr/bin/env python3
"""Regenerate packed_heightmap.png + indirection_heightmap.png from heightmap.png.

The game never reads heightmap.png directly. It renders terrain from a packed
tile atlas addressed through an indirection texture (see heightmap.heightmap).
Normally only the in-game map editor can regenerate these, which means every
scripted edit to heightmap.png is invisible in-game until someone repacks.
This tool replicates the engine's packing scheme (reverse-engineered from the
existing files) so the whole pipeline can stay scripted.

Format (verified empirically against the shipped files, mean reconstruction
error 0.59 grey levels, exact on full-detail tiles):

- The map is split into 32x32-pixel patches; indirection_heightmap.png has one
  RGBA texel per patch (256x128 for an 8192x4096 map).
- Each patch stores a 33x33 block (32 + 1px border shared with the next patch)
  point-sampled down by a factor f in {1,2,4,8,16} -> a (32/f+1)^2 tile.
- Texel channels: R = tile column, G = tile row (within the level's band),
  B = f, A = level index (f = 2^A).
- Tiles for level A live in a horizontal band of the atlas; bands are stacked
  bottom-up starting with level 0 at the image bottom. level_offsets in
  heightmap.heightmap gives each band's y offset measured from the bottom.
  A tile's pixel position is:
      x = R * (32/f + 1)
      y = atlas_height - level_offset[A] - (G + 1) * (32/f + 1)
- Rows hold at most min(atlas_width // tile_px, 256) tiles (R and G are bytes).

Level selection here: coarsest level whose bilinear reconstruction stays
within --tolerance grey levels of the source patch (flat sea packs 16x).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parents[1]
MAP_DATA = ROOT / "map_data"

PATCH = 32
ATLAS_WIDTH = 1386  # keep the width the shipped atlas used
LEVELS = 5


def upsample(tile: np.ndarray) -> np.ndarray:
    if tile.shape == (PATCH + 1, PATCH + 1):
        return tile.astype(np.float32)
    im = Image.fromarray(tile).resize((PATCH + 1, PATCH + 1), Image.BILINEAR)
    return np.asarray(im, dtype=np.float32)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes. Omit for a dry run.")
    parser.add_argument("--tolerance", type=float, default=1.5,
                        help="Max abs reconstruction error allowed when coarsening a patch (default 1.5).")
    args = parser.parse_args()

    hm = np.asarray(Image.open(MAP_DATA / "heightmap.png").convert("L"))
    height, width = hm.shape
    if height % PATCH or width % PATCH:
        raise SystemExit(f"heightmap size {width}x{height} not a multiple of {PATCH}")
    patches_x, patches_y = width // PATCH, height // PATCH
    if patches_x > 256 or patches_y > 256:
        raise SystemExit("indirection coordinates would exceed one byte")

    # 1px edge replication so border patches can read their 33rd row/column.
    padded = np.pad(hm, ((0, 1), (0, 1)), mode="edge")

    # Pick a level for every patch.
    levels = np.zeros((patches_y, patches_x), dtype=np.uint8)
    tiles: dict[int, list[tuple[int, int, np.ndarray]]] = {l: [] for l in range(LEVELS)}
    for py in range(patches_y):
        for px in range(patches_x):
            ref = padded[py * PATCH: py * PATCH + PATCH + 1,
                         px * PATCH: px * PATCH + PATCH + 1]
            level = 0
            for cand in range(LEVELS - 1, 0, -1):
                f = 1 << cand
                small = ref[::f, ::f]
                if np.abs(upsample(small) - ref).max() <= args.tolerance:
                    level = cand
                    break
            levels[py, px] = level
            f = 1 << level
            tiles[level].append((py, px, ref[::f, ::f]))

    counts = {l: len(tiles[l]) for l in range(LEVELS)}
    print("patches per level:", counts)

    # Band layout, level 0 at the bottom of the atlas.
    offsets: list[int] = []
    band_rows: dict[int, int] = {}
    row_caps: dict[int, int] = {}
    cursor = 0
    for level in range(LEVELS):
        tile_px = PATCH // (1 << level) + 1
        cap = min(ATLAS_WIDTH // tile_px, 256)
        rows = -(-len(tiles[level]) // cap) if tiles[level] else 0
        if rows > 256:
            raise SystemExit(f"level {level} needs {rows} rows; exceeds byte-addressable range")
        offsets.append(cursor)
        band_rows[level] = rows
        row_caps[level] = cap
        cursor += rows * tile_px
    atlas_height = cursor
    print(f"atlas: {ATLAS_WIDTH}x{atlas_height}, level offsets {offsets}")

    atlas = np.zeros((atlas_height, ATLAS_WIDTH), dtype=np.uint8)
    indirection = np.zeros((patches_y, patches_x, 4), dtype=np.uint8)
    for level in range(LEVELS):
        tile_px = PATCH // (1 << level) + 1
        cap = row_caps[level]
        for index, (py, px, tile) in enumerate(tiles[level]):
            col, row = index % cap, index // cap
            x0 = col * tile_px
            y0 = atlas_height - offsets[level] - (row + 1) * tile_px
            atlas[y0:y0 + tile_px, x0:x0 + tile_px] = tile
            indirection[py, px] = (col, row, 1 << level, level)

    # Verify by full decode.
    worst = 0.0
    for py in range(patches_y):
        for px in range(patches_x):
            col, row, f, level = (int(v) for v in indirection[py, px])
            tile_px = PATCH // f + 1
            x0 = col * tile_px
            y0 = atlas_height - offsets[level] - (row + 1) * tile_px
            tile = atlas[y0:y0 + tile_px, x0:x0 + tile_px]
            ref = padded[py * PATCH: py * PATCH + PATCH + 1,
                         px * PATCH: px * PATCH + PATCH + 1]
            worst = max(worst, float(np.abs(upsample(tile) - ref).max()))
    print(f"decode-verify worst patch error: {worst:.2f} (tolerance {args.tolerance})")
    if worst > args.tolerance:
        raise SystemExit("verification failed; not writing")

    descriptor = MAP_DATA / "heightmap.heightmap"
    raw = descriptor.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    text = text.replace("\r\n", "\n")
    offsets_str = "".join(f"{{ 0 {off} }}" for off in offsets)
    new_text, n = re.subn(r"level_offsets=\{.*?\}\}", f"level_offsets={{ {offsets_str}}}", text)
    if n != 1:
        raise SystemExit("could not rewrite level_offsets in heightmap.heightmap")

    if args.apply:
        Image.fromarray(atlas, mode="L").save(MAP_DATA / "packed_heightmap.png")
        Image.fromarray(indirection, mode="RGBA").save(MAP_DATA / "indirection_heightmap.png")
        out = new_text.replace("\n", newline).encode("utf-8")
        if bom:
            out = b"\xef\xbb\xbf" + out
        descriptor.write_bytes(out)
        print("packed_heightmap.png, indirection_heightmap.png, heightmap.heightmap written")
    else:
        print("Dry run only. Re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
