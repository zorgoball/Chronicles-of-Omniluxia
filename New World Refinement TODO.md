# Omniluxia New World Refinement TODO

Paste this into a new Codex chat to continue the current Omniluxia New World / second-continent refinement work.

## Goal

Continue refining `new_world_region` so the eastern/New World continent looks and plays closer to the western continent. The original blocker list was: roads, locators, terrain mask painting, province terrain setup, regions/areas splitting, heightmap sculpting, rivers, lakes, and impassables.

The repo is:

`C:\Users\Joshua\Documents\Paradox Interactive\Imperator\mod\Omniluxia`

The main setup file is:

`setup/provinces/00_new_world_region.txt`

## Current Audit Baseline

Latest `python -B tools\audit_second_continent.py` result:

- Region: `new_world_region`
- Areas in region: `92`
- Region provinces: `1119`
- Playable region provinces: `1119`
- Setup entries: `1119`
- Missing definition/setup coverage: `0`
- Missing required setup fields: `0`
- Missing city/fort/great_work/unit_stack/combat/vfx locators: `0`
- Ports in setup listed in `ports.csv`: `20`
- Missing port locators: `0`
- Roads touching setup provinces: `309`
- Internal road edges: `309`
- Outbound road edges: `0`
- Climate coverage: `1119/1119`
- Default map special provinces inside region:
  - sea zones: `0`
  - lakes: `0`
  - impassable terrain: `0`
- Owned setup provinces: `845`
- Unowned setup provinces: `274`

Latest `python -B tools\audit_new_world_map_layers.py` result:

- New World province pixels: `2362324`
- Province bbox: `x=5856..8117, y=384..3849`
- Heightmap over setup provinces: `min=27, max=169, mean=62.16, stddev=26.29`
- River pixels over setup provinces: `14814`
- Snow mask over sampled setup pixels: `32457/590518 (5.50%)`
- Mountains mask over sampled setup pixels: `83386/590518 (14.12%)`

## What Is Done

### Roads

First-pass New World road network is done.

- `setup/main/02_road_network.txt`
- `309` internal New World road edges
- No outbound road edges

### Locators

First-pass locators are done.

- `gfx/map/map_object_data/city_locators.txt`
- `gfx/map/map_object_data/fort_locators.txt`
- `gfx/map/map_object_data/great_work_locators.txt`
- `gfx/map/map_object_data/unit_stack_locators.txt`
- `gfx/map/map_object_data/combat_locators.txt`
- `gfx/map/map_object_data/port_locators.txt`

Audit reports `0` missing for all required locator categories.

### Ports

Ports are done as a generated first pass.

- `map_data/ports.csv`
- `20` New World ports
- All have port locators

### Province Terrain Setup

Province setup is complete mechanically.

- `setup/provinces/00_new_world_region.txt`
- `1119` setup provinces
- Required fields all present:
  - `terrain`
  - `culture`
  - `religion`
  - `trade_goods`
  - `province_rank`

Current terrain distribution:

- plains: `254`
- jungle: `178`
- forest: `160`
- mountain: `150`
- hills: `77`
- steppes: `70`
- desert: `67`
- farmland: `54`
- eldritch_forest: `37`
- marsh: `27`
- flood_plain: `25`
- coastal_terrain: `20`

### Regions And Areas

Region/area splitting is mechanically complete.

- `map_data/areas.txt`
- `map_data/regions.txt`
- `localization/english/regionnames_l_english.yml`

Important: the New World was split into generated subareas/subregions. `tools/audit_second_continent.py` was updated with `resolve_region_areas()` so `new_world_region` audits still include split `new_world_*_reg*` land regions and exclude New World seas.

### Climate

Climate coverage is complete.

- `map_data/climate.txt`
- `1119/1119` setup provinces covered
- `mild_winter`: `677`
- `normal_winter`: `350`
- `arid`: `92`

### Terrain Mask Painting

A strong generated terrain-mask pass is done and should be treated as a first-pass art layer, not final human painting.

Important tools:

- `tools/generate_new_world_terrain_masks.py`
- `tools/refine_new_world_terrain_masks.py`
- `tools/compare_new_world_terrain_density.py`
- `tools/naturalize_new_world_snow_mountains.py`

Notable improvements already done:

- Increased New World terrain mask density to better match the western continent.
- Added northern snow/ice terrain-mask coverage.
- Naturalized mountain/rock/hill masks so the New World is less naked.
- Fixed the snow mask target bug in `generate_new_world_terrain_masks.py`.

### Ugly Central Mountain/Ruler Area

The ugly straight/ruler-like New World mountain scar was visually treated using existing impassable mountain donor tiles.

Tool:

- `tools/place_new_world_impassable_mountain_ranges.py`

Donor impassable mountain IDs used:

- `5752`
- `5751`
- `3074`
- `5743`
- `5745`

Target impassable IDs visually covered:

- `1067`
- `1668`
- `1627`
- `598`

Important caveat: this was a visual terrain/heightmap/mask treatment. It did not convert New World setup provinces into impassable terrain and did not redraw `provinces.png`.

### Rivers

Rivers are now done as a first-pass art-copy layer.

Files/tools:

- `map_data/rivers.png`
- `tools/copy_western_river_shapes_to_new_world.py`
- `tools/generate_new_world_rivers.py`

The first synthetic port-routing approach looked too straight and clustered. It was replaced. The current approach extracts connected river components from the western continent, transforms/flips/scales/rotates them, and stamps them onto New World land. This better matches existing western river silhouettes.

Current river result:

- New World river pixels: `14814`
- Copy pass is idempotent: dry-run after apply reports `0` pixels to change.
- `tools/generate_new_world_rivers.py` is now just a compatibility wrapper around `copy_western_river_shapes_to_new_world.py`.

To regenerate:

`python -B tools\copy_western_river_shapes_to_new_world.py --apply`

or:

`python -B tools\generate_new_world_rivers.py --apply`

## What Still Needs Work

### 1. In-Game Visual QA (main remaining item)

Launch the mod and inspect the New World at multiple zoom levels:

- lakes render as water with sane shores (8 new lakes, see below)
- rivers render and sit in their burned valleys
- terrain no longer shows contour-ring terracing
- packed heightmap loads (terrain relief visible at all zooms)
- beach/seafloor masks look right around lakes and coasts
- snow line and desert edges blend
- run `imperator-tiger.exe` on Windows for a full lint

### 2. Optional Follow-Ups

- More/other lakes: rerun the site selection and `apply_new_world_lakes.py` + `carve_new_world_lake_basins.py`.
- Country assignment for the 274 -> 263 unowned provinces was deliberately skipped (decision: intentional wilderness).

## Update (2026-07-01 session)

### Lakes: DONE

The old 7 clustered candidates were scrapped (climate restored for them). 8 new
spread-out gameplay lakes across every major landmass:

`471 581 1103 1204 2453 2835 4851 5408`

- `map_data/default.map` lakes list (region section)
- removed from setup, climate, areas.txt (matching lake 5564 convention)
- city/fort/great_work/port locators removed; unit_stack/combat/vfx kept-or-added
  (lakes are crossable water, matching 5564)
- heightmap basins carved below the waterline: `tools/carve_new_world_lake_basins.py`

### True Gameplay Impassables: DONE

11 impassables applied earlier via `tools/apply_new_world_impassables.py`:
`1161 2189 2352 2393 2506 2601 2606 2777 3182 3275 3369`

Note: `apply_new_world_lakes.py` used to clobber the impassable_terrain line in
default.map's region section; it is patched to preserve it now.

### Rivers: RESTORED

The working tree had lost the river copy pass (0 river pixels). Re-applied with
`tools/copy_western_river_shapes_to_new_world.py --apply` (14,743 px, idempotent).

### Packed Heightmap: SOLVED (this was why heightmap work never showed in-game)

The game renders from `packed_heightmap.png` + `indirection_heightmap.png`, not
`heightmap.png`. These were stale since the last in-editor repack, so ALL
scripted heightmap edits were invisible in-game.

`tools/repack_packed_heightmap.py --apply` now regenerates both files plus the
`level_offsets` in `heightmap.heightmap` (format reverse-engineered and verified
against the shipped files; decode-verify worst error 1.0 grey level).

RUN THIS AFTER EVERY heightmap.png EDIT.

### Heightmap Polish: DONE

`tools/polish_new_world_heightmap.py --apply`:
- de-terraced the contour-ring artifacts across the whole New World
- added elevation-scaled multi-octave relief noise
- burned shallow valleys under all river pixels
- protected coastlines, lake basins, sea floor

### Terrain Mask Polish: DONE

`tools/polish_new_world_terrain_masks.py --apply`:
- beach mask around lake shores and coastal seams (matched to western profile)
- seafloor mask under New World coastal water and lakes (east had none)
- feathered snow/desert/dunes mask edges

### Ownership: DECIDED

263 unowned provinces stay as intentional wilderness.

## Useful Commands

- `python -B tools\audit_second_continent.py`
- `python -B tools\audit_new_world_map_layers.py`
- `python -B tools\copy_western_river_shapes_to_new_world.py --apply`
- `python -B tools\carve_new_world_lake_basins.py --apply`
- `python -B tools\polish_new_world_heightmap.py --apply`
- `python -B tools\polish_new_world_terrain_masks.py --apply`
- `python -B tools\repack_packed_heightmap.py --apply`  (always last after heightmap edits)

Workflow note: if rerunning mountain tools, run
`naturalize_new_world_snow_mountains.py --apply` before
`place_new_world_impassable_mountain_ranges.py --apply`, then re-run the polish
and repack tools.
