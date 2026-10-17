"""Builds the Chronicles of Omniluxia update trailer from the mod's own assets.

Everything on screen comes out of the repository at REF: the in-engine loading
screens, the world map (rendered from map_data heightmap + terrain masks), the
spell/trait/wonder icons and the map font. Music is the mod's main theme.

Usage: python3 trailer/make_trailer.py [REF] [OUT.mp4]
Needs: git, ffmpeg, numpy, Pillow.
"""
import io
import math
import os
import re
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REF = sys.argv[1] if len(sys.argv) > 1 else "origin/wiki-site"
OUT = sys.argv[2] if len(sys.argv) > 2 else "trailer/omniluxia_update_trailer.mp4"
W, H, FPS = 1920, 1080, 30
DUR = 29.5
MUSIC_START = 24.0  # quiet breakdown in the theme; first big hit lands at 28.46s
GOLD = (236, 204, 138)
CREAM = (240, 232, 214)

# Cut points = strong onsets in the theme, minus MUSIC_START.
CUTS = [0.0, 4.46, 7.38, 10.68, 13.60, 16.16, 19.64, 22.38, 25.31, DUR]
BEAT = 0.3715


def git_bytes(path):
    return subprocess.run(["git", "show", f"{REF}:{path}"], check=True, capture_output=True).stdout


def git_img(path):
    return Image.open(io.BytesIO(git_bytes(path)))


def ease(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


FONT_PATH = "/tmp/_omni_mapfont.ttf"
with open(FONT_PATH, "wb") as f:
    f.write(git_bytes("fonts/mapfont.ttf"))


def font(size):
    return ImageFont.truetype(FONT_PATH, size)


# ---------------------------------------------------------------- world map
def render_world():
    w, h = 4096, 2048
    hm = np.array(git_img("map_data/heightmap.png").convert("L").resize((w, h), Image.BILINEAR)).astype(np.float32)
    cols = {
        "grass_plain": (92, 112, 58), "grass_2": (84, 106, 52), "grass_dry": (140, 130, 82),
        "farmlands": (122, 118, 70), "forest_floor": (50, 70, 40), "woodlands": (56, 78, 42),
        "desert": (196, 170, 118), "dunes": (210, 180, 126), "beach": (200, 184, 146),
        "mountains": (112, 104, 94), "rock_european": (120, 112, 100), "snow": (220, 224, 230),
        "marshlands_europe": (74, 90, 62), "magma": (170, 64, 24), "hardened_lava": (52, 44, 40),
    }
    acc = np.zeros((h, w, 3), np.float32)
    wsum = np.full((h, w), 1e-3, np.float32)
    for k, c in cols.items():
        m = np.array(git_img(f"gfx/map/terrain/{k}_mask.png").convert("L").resize((w, h))).astype(np.float32) / 255
        acc += m[..., None] * np.array(c, np.float32)
        wsum += m
    base = acc / wsum[..., None]
    base[wsum < 0.05] = (100, 110, 66)
    hs = np.array(Image.fromarray(hm.astype("uint8")).filter(ImageFilter.GaussianBlur(1.2))).astype(np.float32)
    gy, gx = np.gradient(hs)
    shade = np.clip(1 + (-gx - gy) * 0.09, 0.55, 1.25)
    land = hm > 1.5
    dist = np.array(Image.fromarray((land * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(22))).astype(np.float32) / 255
    deep, shallow = np.array([10, 26, 44], np.float32), np.array([34, 82, 100], np.float32)
    water = deep + (shallow - deep) * np.clip(dist * 2.0, 0, 1)[..., None]
    out = np.where(land[..., None], base * shade[..., None], water)
    return Image.fromarray(np.clip(out, 0, 255).astype("uint8"))


def new_world_glow():
    """Gold overlay over every province in the regions carved out of the old New World mega region."""
    regions = ["great_mushroom_island", "minor_mushroom_isles", "jade_island_north_region",
               "jade_island_shout_region", "ant_island_west_region", "ant_island_central_region",
               "ant_island_east_region", "arame_island_north_region", "arame_island_west_region",
               "arame_island_east_region", "dragons_point_region", "dragon_steppes_west_region",
               "dragon_steppes_east_region"]

    def blocks(txt):
        out = {}
        for m in re.finditer(r"^([A-Za-z0-9_]+)\s*=\s*\{", txt, re.M):
            d = 0
            for k in range(m.end() - 1, len(txt)):
                d += txt[k] == "{"
                d -= txt[k] == "}"
                if d == 0:
                    out[m.group(1)] = txt[m.end() - 1:k + 1]
                    break
        return out

    reg = blocks(git_bytes("map_data/regions.txt").decode("utf-8-sig"))
    areas = blocks(git_bytes("map_data/areas.txt").decode("utf-8-sig"))
    provs = set()
    for r in regions:
        for a in re.findall(r"[A-Za-z0-9_]+", reg[r].split("{", 2)[2].split("}")[0]):
            if a in areas:
                provs |= set(map(int, re.findall(r"\d+", re.sub(r"#.*", "", areas[a]))))
    keys = []
    for line in git_bytes("map_data/definition.csv").decode("latin-1").splitlines():
        p = line.strip().split(";")
        if p[0].isdigit() and int(p[0]) in provs:
            keys.append(int(p[1]) * 65536 + int(p[2]) * 256 + int(p[3]))
    im = np.array(git_img("map_data/provinces.png").convert("RGB").resize((4096, 2048), Image.NEAREST)).astype(np.int32)
    m = np.isin(im[..., 0] * 65536 + im[..., 1] * 256 + im[..., 2], np.array(keys)).astype(np.float32)
    mi = Image.fromarray((m * 255).astype("uint8"))
    edge = np.abs(m - np.array(mi.filter(ImageFilter.MinFilter(5))).astype(np.float32) / 255)
    glow = np.array(Image.fromarray((edge * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(10))).astype(np.float32) / 255
    a = np.clip(m * 0.16 + edge + glow * 1.6, 0, 1)
    rgba = np.zeros((2048, 4096, 4), np.uint8)
    rgba[..., :3] = (240, 196, 110)
    rgba[..., 3] = (a * 255).astype("uint8")
    ys, xs = np.nonzero(m)
    return Image.fromarray(rgba, "RGBA"), (xs.mean(), ys.mean())


print("rendering world map...")
WORLD = render_world()
NW_GLOW, NW_CENTER = new_world_glow()


def load(n):
    return git_img(f"gfx/loadingscreens/load_{n}.dds").convert("RGB")


LOADS = {n: load(n) for n in (0, 2, 6, 7, 8, 10, 12, 13)}


def icon(path):
    return git_img(path).convert("RGBA")


SPELL_ICONS = [icon(f"gfx/interface/icons/traits/{n}_preview.png") for n in (
    "omnic_diviner_spell_t1_trait", "crimson_flame_trait", "aldic_illusionist_spell_t1_trait",
    "magically_attuned_trait", "omnic_hierophant_spell_t1_trait", "black_flame_trait",
    "stone_magic_trait", "aldic_cleric_spell_t1_trait")]
BATTLE_SPELLS = [icon(f"gfx/interface/icons/modifiers/{n}.dds") for n in (
    "omni_arcane_aegis_spell_mod", "omni_fear_hex_spell_mod", "omni_storm_wrack_spell_mod",
    "omni_siege_burning_pitch_spell_mod", "omni_mudbind_spell_mod", "omni_harbor_ward_mod")]
WONDERS = [(icon(f"gfx/interface/icons/great_work/panel/ancient_wonders/{n}.dds"), t) for n, t in (
    ("skyloom_spire", "Skyloom Spire"), ("tideward_sanctum", "Tideward Sanctum"),
    ("emberforge_bastion", "Emberforge Bastion"), ("heartspore_colossus", "Heartspore Colossus"),
    ("shadowmoon_ziggurat", "Shadowmoon Ziggurat"), ("deepstone_vault", "Deepstone Vault"))]


# ---------------------------------------------------------------- helpers
def ken_burns(img, t, z0, z1, c0, c1):
    """Crop img around a moving centre (fractions) at zoom z (1 = fit width) and scale to frame."""
    e = t * t * (3 - 2 * t)
    z = z0 + (z1 - z0) * e
    cx = c0[0] + (c1[0] - c0[0]) * e
    cy = c0[1] + (c1[1] - c0[1]) * e
    iw, ih = img.size
    cw = min(iw, ih * W / H) / z
    ch = cw * H / W
    x0 = min(max(cx * iw - cw / 2, 0), iw - cw)
    y0 = min(max(cy * ih - ch / 2, 0), ih - ch)
    return img.transform((W, H), Image.EXTENT, (x0, y0, x0 + cw, y0 + ch), Image.BICUBIC)


_vig = None


def vignette(frame, strength=0.55):
    global _vig
    if _vig is None:
        y, x = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((x - W / 2) / (W / 2)) ** 2 + ((y - H / 2) / (H / 2)) ** 2)
        _vig = np.clip(1 - (r - 0.45) * 0.9, 0, 1)
    a = np.asarray(frame).astype(np.float32)
    v = 1 - strength * (1 - _vig)
    return Image.fromarray(np.clip(a * v[..., None], 0, 255).astype("uint8"))


def darken(frame, k):
    return Image.fromarray((np.asarray(frame).astype(np.float32) * k).astype("uint8"))


def grade(frame, warm=0.06):
    a = np.asarray(frame).astype(np.float32)
    a = (a - 128) * 1.08 + 128
    a[..., 0] *= 1 + warm
    a[..., 2] *= 1 - warm
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))


def text(frame, s, size, xy, t, anchor="mm", color=GOLD, spacing=0, delay=0.0, dur=0.35, out_t=None):
    """Fade-and-rise text. t is seconds since scene start."""
    a = ease((t - delay) / dur)
    if out_t is not None:
        a *= 1 - ease((t - out_t) / 0.25)
    if a <= 0:
        return
    f = font(size)
    if spacing:
        s = (" " * spacing).join(s) if spacing > 0 else s
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x, y = xy[0], xy[1] + (1 - a) * 18
    d.text((x + 3, y + 4), s, font=f, fill=(0, 0, 0, int(200 * a)), anchor=anchor)
    shadow = layer.filter(ImageFilter.GaussianBlur(6))
    d2 = ImageDraw.Draw(shadow)
    d2.text((x, y), s, font=f, fill=color + (int(255 * a),), anchor=anchor)
    frame.paste(shadow, (0, 0), shadow)


def rule(frame, y, t, width=520, delay=0.1):
    a = ease((t - delay) / 0.4)
    if a <= 0:
        return
    d = ImageDraw.Draw(frame, "RGBA")
    hw = width / 2 * a
    d.line([(W / 2 - hw, y), (W / 2 + hw, y)], fill=GOLD + (int(220 * a),), width=2)
    d.polygon([(W / 2, y - 6), (W / 2 + 6, y), (W / 2, y + 6), (W / 2 - 6, y)], fill=GOLD + (int(255 * a),))


def caption_block(frame, t, kicker, head, sub, y=800, out_t=None):
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = np.zeros((H, W, 4), np.uint8)
    ramp = np.clip((np.arange(H) - (y - 260)) / 300, 0, 1) * 170
    g[..., 3] = ramp[:, None].astype("uint8")
    shade = Image.fromarray(g, "RGBA")
    frame.paste(shade, (0, 0), shade)
    text(frame, kicker, 34, (W / 2, y - 96), t, color=GOLD, spacing=1, out_t=out_t)
    text(frame, head, 92, (W / 2, y), t, color=CREAM, delay=0.06, out_t=out_t)
    rule(frame, y + 66, t, delay=0.12)
    text(frame, sub, 36, (W / 2, y + 112), t, color=GOLD, delay=0.18, out_t=out_t)


def paste_icon(frame, ic, cx, cy, size, a, glow=True):
    if a <= 0:
        return
    s = max(2, int(size * (0.6 + 0.4 * ease(a))))
    im = ic.resize((s, s), Image.LANCZOS)
    alpha = np.asarray(im.split()[3]).astype(np.float32) * min(1, a)
    im.putalpha(Image.fromarray(alpha.astype("uint8")))
    if glow:
        g = Image.new("RGBA", (s + 80, s + 80), (0, 0, 0, 0))
        g.paste(Image.new("RGBA", (s, s), GOLD + (int(120 * min(1, a)),)), (40, 40), im)
        g = g.filter(ImageFilter.GaussianBlur(18))
        frame.paste(g, (int(cx - s / 2 - 40), int(cy - s / 2 - 40)), g)
    frame.paste(im, (int(cx - s / 2), int(cy - s / 2)), im)


def letterbox(frame):
    d = ImageDraw.Draw(frame)
    d.rectangle([0, 0, W, 54], fill=(0, 0, 0))
    d.rectangle([0, H - 54, W, H], fill=(0, 0, 0))
    return frame


def world_view(t, z0, z1, c0, c1, glow=0.0):
    img = ken_burns(WORLD, t, z0, z1, c0, c1)
    if glow > 0:
        g = ken_burns(NW_GLOW, t, z0, z1, c0, c1)
        a = np.asarray(g.split()[3]).astype(np.float32) * glow
        g.putalpha(Image.fromarray(np.clip(a, 0, 255).astype("uint8")))
        img = img.convert("RGBA")
        img.alpha_composite(g)
        img = img.convert("RGB")
    return img


# ---------------------------------------------------------------- scenes
NWC = (NW_CENTER[0] / 4096, NW_CENTER[1] / 2048)


def s_open(t, d):
    f = world_view(t / d, 1.0, 1.35, (0.5, 0.5), (0.62, 0.52))
    f = vignette(darken(f, 0.55 + 0.2 * ease(t / d)), 0.7)
    text(f, "Two years since the last major update...", 56, (W / 2, H / 2 - 30), t, color=CREAM, delay=0.5, dur=0.6, out_t=2.3)
    text(f, "the world has changed.", 72, (W / 2, H / 2), t, color=GOLD, delay=2.55, dur=0.5)
    return f


def s_newworld(t, d):
    f = world_view(t / d, 1.9, 3.0, (0.66, 0.5), NWC, glow=0.25 + 0.75 * ease(t / 0.9) * (0.85 + 0.15 * math.sin(t * 6)))
    f = vignette(f, 0.5)
    caption_block(f, t, "THE NEW WORLD", "A New World to Conquer", "13 New Regions  ·  45 New Formable Nations  ·  New Holy Sites")
    return f


def s_peoples(t, d):
    f = grade(ken_burns(LOADS[7], t / d, 1.05, 1.22, (0.5, 0.45), (0.46, 0.5)))
    f = vignette(f)
    caption_block(f, t, "A FULL RACIAL SYSTEM", "New Peoples Rise", "Orcish Faiths & Governments  ·  Snakefolk  ·  Ishtari  ·  New Cultures")
    return f


def s_magic(t, d):
    bg = ken_burns(LOADS[0], t / d, 1.15, 1.3, (0.4, 0.5), (0.5, 0.45)).filter(ImageFilter.GaussianBlur(3))
    a = np.asarray(bg).astype(np.float32) * 0.42
    a[..., 0] *= 0.8
    a[..., 2] = a[..., 2] * 1.25 + 14
    f = vignette(Image.fromarray(np.clip(a, 0, 255).astype("uint8")), 0.7)
    n = len(SPELL_ICONS)
    for i, ic in enumerate(SPELL_ICONS):
        ang = -math.pi / 2 + (i - (n - 1) / 2) * 0.33
        cx = W / 2 + math.cos(ang) * 620 + 0
        cy = 760 + math.sin(ang) * 520
        paste_icon(f, ic, cx, cy, 150, (t - i * BEAT / 2) / 0.25)
    caption_block(f, t, "A FULL MAGIC SYSTEM", "Study. Learn. Cast.", "Battle, Siege & Civic Spells  ·  Magic Academies  ·  Battle-Magic AI", y=830)
    return f


def s_raid(t, d):
    f = grade(ken_burns(LOADS[2], t / d, 1.1, 1.3, (0.5, 0.5), (0.56, 0.44)), warm=0.1)
    f = vignette(f)
    caption_block(f, t, "RAIDING & PIRACY", "Raid. Pillage. Plunder.", "Raze & Pillage Provinces  ·  Engage in Piracy  ·  Build Pirate Havens")
    return f


def s_wonders(t, d):
    bg = ken_burns(LOADS[10], t / d, 1.2, 1.35, (0.5, 0.5), (0.5, 0.42)).filter(ImageFilter.GaussianBlur(4))
    f = vignette(darken(bg, 0.45), 0.7)
    for i, (ic, name) in enumerate(WONDERS):
        col, row = i % 3, i // 3
        cx, cy = W / 2 + (col - 1) * 300, 270 + row * 290
        a = (t - i * BEAT / 1.5) / 0.3
        paste_icon(f, ic, cx, cy, 230, a, glow=False)
        text(f, name, 26, (cx, cy + 132), t, color=CREAM, delay=i * BEAT / 1.5 + 0.1)
    caption_block(f, t, "GREAT WORKS", "Raise New Wonders", "Omniluxian Trade Goods Now Build Great Wonders", y=900)
    return f


MARKET = git_img("gfx/interface/event_window/event_generic_marketplace.dds").convert("RGB")
SLOTS = ["Weapon", "Ranged", "Armor", "Shield", "Emblem", "Trinket"]


def s_items(t, d):
    f = grade(ken_burns(MARKET, t / d, 1.0, 1.1, (0.5, 0.55), (0.5, 0.5)), warm=0.08)
    f = vignette(f, 0.6)
    d2 = ImageDraw.Draw(f, "RGBA")
    bw, bh, gap = 230, 84, 24
    x0 = W / 2 - (len(SLOTS) * bw + (len(SLOTS) - 1) * gap) / 2
    for i, name in enumerate(SLOTS):
        a = ease((t - 0.15 - i * BEAT / 2) / 0.2)
        if a <= 0:
            continue
        x, y = x0 + i * (bw + gap), 250 + (1 - a) * 24
        d2.rectangle([x, y, x + bw, y + bh], fill=(14, 12, 10, int(200 * a)), outline=GOLD + (int(255 * a),), width=2)
        text(f, name, 34, (x + bw / 2, 250 + bh / 2), t, color=CREAM, delay=0.15 + i * BEAT / 2, dur=0.2)
    caption_block(f, t, "ITEMS & CITY VISITS", "Equip Your Rulers",
                  "Visit Cities  ·  Shop the Markets & Black Markets  ·  1,040 Items to Collect")
    return f


RAPID = [(13, "The Razani Civil War"), (12, "Vampire Dominions"), (8, "Adventures"), (6, "Trade Expeditions")]


def s_rapid(t, d):
    seg = d / len(RAPID)
    i = min(int(t / seg), len(RAPID) - 1)
    lt = t - i * seg
    n, label = RAPID[i]
    f = grade(ken_burns(LOADS[n], lt / seg, 1.25, 1.12, (0.5, 0.5), (0.5, 0.5)))
    f = vignette(darken(f, 0.85))
    text(f, "AND MORE", 34, (W / 2, H / 2 - 110), t, color=GOLD, spacing=1, dur=0.15)
    text(f, label, 104, (W / 2, H / 2 + 20), lt, color=CREAM, dur=0.12)
    return f


def s_title(t, d):
    f = world_view(t / d, 1.25, 1.05, (0.55, 0.5), (0.5, 0.5), glow=0.35)
    f = vignette(darken(f, 0.42), 0.8)
    text(f, "CHRONICLES OF", 54, (W / 2, H / 2 - 110), t, color=GOLD, spacing=1, delay=0.05, dur=0.5)
    text(f, "OMNILUXIA", 168, (W / 2, H / 2 + 10), t, color=CREAM, delay=0.15, dur=0.6)
    rule(f, H / 2 + 110, t, width=760, delay=0.4)
    text(f, "A Total Conversion for Imperator: Rome", 40, (W / 2, H / 2 + 165), t, color=GOLD, delay=0.7, dur=0.5)
    return f


SCENES = [s_open, s_newworld, s_peoples, s_magic, s_raid, s_items, s_wonders, s_rapid, s_title]


def frame_at(time):
    for i in range(len(SCENES)):
        if CUTS[i] <= time < CUTS[i + 1]:
            t = time - CUTS[i]
            f = SCENES[i](t, CUTS[i + 1] - CUTS[i])
            # white flash + punch on every hit after the cold open
            if i > 0 and t < 0.12:
                a = (1 - t / 0.12) * 0.55
                f = Image.blend(f, Image.new("RGB", (W, H), (255, 244, 224)), a)
            break
    else:
        f = Image.new("RGB", (W, H))
    if time < 0.5:
        f = darken(f, time / 0.5)
    if time > DUR - 0.8:
        f = darken(f, max(0, (DUR - time) / 0.8))
    return letterbox(f)


def main():
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    music = "/tmp/_omni_theme.ogg"
    with open(music, "wb") as fh:
        fh.write(git_bytes("music/Shardul_Zorgo_mix_2.ogg"))
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-ss", str(MUSIC_START), "-t", str(DUR), "-i", music,
           "-af", f"afade=t=in:st=0:d=0.4,afade=t=out:st={DUR - 2.2}:d=2.2",
           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", OUT]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    total = int(DUR * FPS)
    for k in range(total):
        p.stdin.write(frame_at(k / FPS).tobytes())
        if k % 60 == 0:
            print(f"frame {k}/{total}", flush=True)
    p.stdin.close()
    p.wait()
    print("wrote", OUT)


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[3] == "--stills":
        for s in [float(x) for x in sys.argv[4:]]:
            frame_at(s).save(f"{os.path.splitext(OUT)[0]}_{s:05.2f}.png")
    else:
        main()
