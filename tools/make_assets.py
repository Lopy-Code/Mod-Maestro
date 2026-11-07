"""Génère toute l'identité visuelle de ModMaestro (SVG + PNG) dans ./assets.

Usage :  python tools/make_assets.py
Dépendances : rsvg-convert (librsvg) pour les PNG, Pillow pour le .ico — facultatifs :
sans eux, seuls les SVG sont écrits.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets")
ILLU = os.path.join(OUT, "illustrations")

C30 = math.cos(math.radians(30))

# -- Palette ("papier chaud" + terracotta) ------------------------------------
PAL = {
    "coral": ("#E8997B", "#D97757", "#B85C3E"),   # dessus, gauche, droite
    "sand":  ("#F0E6CF", "#DDCEAA", "#C3B28A"),
    "sage":  ("#B3C8A4", "#92AB83", "#738C68"),
    "sky":   ("#B1C7DC", "#8FAAC4", "#718DA9"),
    "ink":   ("#6A675F", "#4C4A44", "#363430"),
    "cream": ("#FFF9EF", "#F3DAC6", "#E3BDA2"),
}
INK, CORAL, CREAM, PAPER = "#1F1E1D", "#D97757", "#F4F1E8", "#FAF9F5"

_uid = [0]


def _rounded_poly(points, r):
    """Polygone aux coins arrondis (courbes de Bézier quadratiques)."""
    n = len(points)
    d = []
    for i in range(n):
        p0, p1, p2 = points[i - 1], points[i], points[(i + 1) % n]

        def toward(a, b, dist):
            vx, vy = b[0] - a[0], b[1] - a[1]
            ln = math.hypot(vx, vy) or 1
            return (a[0] + vx / ln * dist, a[1] + vy / ln * dist)

        a = toward(p1, p0, r)
        b = toward(p1, p2, r)
        d.append(("M" if i == 0 else "L") + f"{a[0]:.2f},{a[1]:.2f}")
        d.append(f"Q{p1[0]:.2f},{p1[1]:.2f} {b[0]:.2f},{b[1]:.2f}")
    return " ".join(d) + " Z"


def box(x, y, s, h, pal, rounding=0.13, opacity=1.0, extra=""):
    """Pavé isométrique. (x, y) = centre du losange du dessus, s = arête, h = hauteur."""
    dx = s * C30
    top = [(x, y - s / 2), (x + dx, y), (x, y + s / 2), (x - dx, y)]
    left = [(x - dx, y), (x, y + s / 2), (x, y + s / 2 + h), (x - dx, y + h)]
    right = [(x + dx, y), (x + dx, y + h), (x, y + s / 2 + h), (x, y + s / 2)]
    sil = [(x, y - s / 2), (x + dx, y), (x + dx, y + h), (x, y + s / 2 + h), (x - dx, y + h), (x - dx, y)]
    _uid[0] += 1
    cid = f"c{_uid[0]}"

    def pts(p):
        return " ".join(f"{a:.2f},{b:.2f}" for a, b in p)

    r = s * rounding
    return (
        f'<g opacity="{opacity}" {extra}><clipPath id="{cid}"><path d="{_rounded_poly(sil, r)}"/></clipPath>'
        f'<g clip-path="url(#{cid})">'
        f'<polygon points="{pts(left)}" fill="{pal[1]}"/>'
        f'<polygon points="{pts(right)}" fill="{pal[2]}"/>'
        f'<polygon points="{pts(top)}" fill="{pal[0]}"/>'
        f"</g></g>"
    )


def cube(cx, cy, s, pal, **kw):
    """Cube dont (cx, cy) est le centre de la silhouette."""
    return box(cx, cy - s / 2, s, s, pal, **kw)


def cube_outline(cx, cy, s, color, width=3, dash="7 6", opacity=1.0):
    dx = s * C30
    sil = [(cx, cy - s), (cx + dx, cy - s / 2), (cx + dx, cy + s / 2), (cx, cy + s), (cx - dx, cy + s / 2), (cx - dx, cy - s / 2)]
    inner = [(cx - dx, cy - s / 2), (cx, cy), (cx + dx, cy - s / 2)], [(cx, cy), (cx, cy + s)]
    d = _rounded_poly(sil, s * 0.13)
    lines = "".join(
        f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in seg)}" />' for seg in inner)
    return (f'<g fill="none" stroke="{color}" stroke-width="{width}" stroke-dasharray="{dash}" '
            f'stroke-linecap="round" stroke-linejoin="round" opacity="{opacity}"><path d="{d}"/>{lines}</g>')


def spark(x, y, r, color=CORAL, opacity=1.0):
    k = r * 0.28
    d = (f"M{x},{y - r} Q{x + k},{y - k} {x + r},{y} Q{x + k},{y + k} {x},{y + r} "
         f"Q{x - k},{y + k} {x - r},{y} Q{x - k},{y - k} {x},{y - r} Z")
    return f'<path d="{d}" fill="{color}" opacity="{opacity}"/>'


def shadow(cx, cy, rx, ry=None, opacity=0.10):
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry or rx * 0.32}" fill="{INK}" opacity="{opacity}"/>'


def svg(w, h, body, extra=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" {extra}>'
            f"{body}</svg>\n")


# ----------------------------------------------------------------------------
# Logo
# ----------------------------------------------------------------------------

def logo_icon(size=512, rounded=True):
    s = 118
    body = (
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#EDA283"/><stop offset="1" stop-color="#C3593A"/></linearGradient>'
        '<radialGradient id="glow" cx="0.3" cy="0.2" r="0.8"><stop offset="0" stop-color="#fff" stop-opacity="0.28"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient></defs>'
        f'<rect width="512" height="512" rx="{116 if rounded else 0}" fill="url(#bg)"/>'
        f'<rect width="512" height="512" rx="{116 if rounded else 0}" fill="url(#glow)"/>'
        + shadow(250, 424, 118, 30, 0.16)
        + cube(244, 296, s, PAL["cream"], rounding=0.15)
        # baton (la baguette du chef d'orchestre)
        + '<path d="M276 222 L376 128" stroke="#2A211C" stroke-width="15" stroke-linecap="round"/>'
        + '<circle cx="272" cy="226" r="11" fill="#2A211C"/>'
        + spark(392, 112, 38, "#FFF3E4")
        + spark(332, 78, 15, "#FFE2CC", 0.9)
        + spark(430, 176, 11, "#FFE2CC", 0.8)
    )
    return svg(512, 512, body)


def logo_mark():
    """Pictogramme seul, sans fond (favicon, monochrome)."""
    body = (cube(256, 276, 150, PAL["coral"], rounding=0.15)
            + '<path d="M300 170 L402 78" stroke="#2A211C" stroke-width="16" stroke-linecap="round"/>'
            + spark(418, 62, 40, CORAL))
    return svg(512, 512, body)


def logo_lockup():
    icon = logo_icon().replace('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512" >', "").replace("</svg>\n", "")
    body = (f'<g transform="scale(0.5)">{icon}</g>'
            f'<text x="290" y="168" font-family="Iowan Old Style, Palatino Linotype, Georgia, serif" font-size="112" '
            f'font-weight="600" fill="{INK}" letter-spacing="-2">Mod<tspan fill="{CORAL}">Maestro</tspan></text>')
    return svg(1100, 256, body)


# ----------------------------------------------------------------------------
# Scène isométrique (hero / bannière)
# ----------------------------------------------------------------------------

def voxel_scene(cx, cy, s, heights, colors, graph=True):
    dx = s * C30
    items = []
    for i, row in enumerate(heights):
        for j, hgt in enumerate(row):
            for k in range(hgt):
                x = cx + (i - j) * dx
                y = cy + (i + j) * s / 2 - k * s
                items.append((i + j + k, k, i, j, x, y))
    items.sort()
    out, tops = [], {}
    for _, k, i, j, x, y in items:
        pal = PAL[colors.get((i, j, k), "sand")]
        out.append(cube(x, y, s, pal, rounding=0.12))
        tops[(i, j)] = (x, y - s)
    lines = ""
    if graph:
        pts = [tops[key] for key in sorted(tops)]
        links = [(0, 5), (5, 10), (10, 15), (3, 6), (6, 9), (9, 12), (1, 6), (2, 11)]
        for a, b in links:
            if a < len(pts) and b < len(pts):
                (x1, y1), (x2, y2) = pts[a], pts[b]
                lines += (f'<path d="M{x1:.0f},{y1 - 6:.0f} Q{(x1 + x2) / 2:.0f},{min(y1, y2) - 46:.0f} {x2:.0f},{y2 - 6:.0f}" '
                          f'stroke="{INK}" stroke-opacity="0.35" stroke-width="2" stroke-dasharray="3 7" '
                          f'stroke-linecap="round" fill="none"/>')
    return "".join(out), lines, tops


def hero_body(w=960, h=560, ox=0, oy=0):
    heights = [
        [1, 1, 1, 1],
        [1, 2, 2, 1],
        [1, 2, 3, 1],
        [1, 1, 1, 2],
    ]
    colors = {
        (2, 2, 2): "coral", (2, 2, 1): "sand", (1, 2, 1): "sage", (2, 1, 1): "sky",
        (1, 1, 1): "cream", (0, 0, 0): "sage", (0, 3, 0): "coral", (3, 0, 0): "sky",
        (3, 3, 0): "ink", (3, 3, 1): "ink", (2, 3, 0): "coral", (3, 2, 0): "cream",
    }
    cubes, _, tops = voxel_scene(w * 0.50 + ox, h * 0.36 + oy, 62, heights, colors, graph=False)
    tx, ty = tops[(2, 2)]
    baton = (f'<path d="M{tx + 18:.0f},{ty - 30:.0f} L{tx + 96:.0f},{ty - 96:.0f}" stroke="#2A211C" stroke-width="9" stroke-linecap="round"/>'
             f'<circle cx="{tx + 16:.0f}" cy="{ty - 28:.0f}" r="7" fill="#2A211C"/>'
             + spark(tx + 112, ty - 112, 26, CORAL) + spark(tx + 62, ty - 150, 11, CORAL, 0.8)
             + spark(tx + 150, ty - 66, 9, CORAL, 0.7))
    # petits cubes « dépendances » reliés à la tour par des pointillés
    nodes = [(w * 0.26 + ox, h * 0.22 + oy, 26, "sand"), (w * 0.88 + ox, h * 0.50 + oy, 22, "sky"),
             (w * 0.84 + ox, h * 0.84 + oy, 18, "coral")]
    links = ""
    for nx, ny, ns, _ in nodes:
        links += (f'<path d="M{tx:.0f},{ty - 4:.0f} Q{(tx + nx) / 2:.0f},{min(ty, ny) - 70:.0f} {nx:.0f},{ny - ns:.0f}" '
                  f'stroke="{INK}" stroke-opacity="0.30" stroke-width="2.2" stroke-dasharray="2 8" '
                  f'stroke-linecap="round" fill="none"/>')
    floating = "".join(cube(nx, ny, ns, PAL[c]) for nx, ny, ns, c in nodes)
    return shadow(w * 0.5 + ox, h * 0.745 + oy, 225, 52, 0.10) + links + cubes + baton + floating


def hero_svg():
    return svg(960, 560, hero_body())


def banner_svg():
    w, h = 1280, 640
    icon = logo_icon().split(">", 1)[1].rsplit("</svg>", 1)[0]
    body = (
        '<defs><linearGradient id="bgb" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#F7F4EC"/>'
        '<stop offset="1" stop-color="#EBE6D8"/></linearGradient></defs>'
        f'<rect width="{w}" height="{h}" fill="url(#bgb)"/>'
        f'<g transform="translate(560 60) scale(0.78)">{hero_body(960, 560)}</g>'
        f'<g transform="translate(84 96) scale(0.25)">{icon}</g>'
        f'<text x="84" y="352" font-family="Iowan Old Style, Palatino Linotype, Georgia, serif" font-size="92" font-weight="600" fill="{INK}" letter-spacing="-2">Mod<tspan fill="{CORAL}">Maestro</tspan></text>'
        f'<text x="88" y="406" font-family="Inter, Segoe UI, Helvetica, Arial, sans-serif" font-size="30" fill="#5E5D57">Le chef d\'orchestre de ton modpack Minecraft.</text>'
        f'<g font-family="Inter, Segoe UI, Helvetica, Arial, sans-serif" font-size="21" fill="#2B2A27">'
        f'<g transform="translate(88 448)"><rect width="168" height="42" rx="21" fill="#FAF9F5" stroke="#DDD8C8"/><text x="84" y="28" text-anchor="middle">Doublons</text></g>'
        f'<g transform="translate(268 448)"><rect width="196" height="42" rx="21" fill="#FAF9F5" stroke="#DDD8C8"/><text x="98" y="28" text-anchor="middle">Dépendances</text></g>'
        f'<g transform="translate(88 502)"><rect width="214" height="42" rx="21" fill="#FAF9F5" stroke="#DDD8C8"/><text x="107" y="28" text-anchor="middle">Incompatibilités</text></g>'
        f'<g transform="translate(314 502)"><rect width="190" height="42" rx="21" fill="#D97757"/><text x="95" y="28" text-anchor="middle" fill="#FFF">Dossier serveur</text></g>'
        f"</g>"
    )
    return svg(w, h, body)


# ----------------------------------------------------------------------------
# Illustrations d'état (320 x 240)
# ----------------------------------------------------------------------------

W, H = 320, 240


def illu_ok():
    return svg(W, H, shadow(160, 206, 96, 20) + cube(70, 168, 20, PAL["sand"]) + cube(246, 172, 16, PAL["ink"])
               + cube(160, 128, 64, PAL["sage"]) + spark(262, 112, 12, CORAL, 0.8)
               + '<circle cx="212" cy="76" r="24" fill="#FAF9F5" stroke="#738C68" stroke-width="4"/>'
               + '<path d="M201 77 L209 85 L224 67" stroke="#5E7A52" stroke-width="6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')


def illu_duplicates():
    return svg(W, H, shadow(160, 208, 104, 20)
               + cube(190, 112, 50, PAL["coral"], opacity=0.45)
               + cube(136, 142, 50, PAL["coral"])
               + f'<path d="M205 175 L225 175 M205 185 L225 185" stroke="{INK}" stroke-opacity="0.45" stroke-width="5" stroke-linecap="round"/>'
               + cube(260, 176, 18, PAL["sand"]) + spark(66, 84, 12, CORAL, 0.8) + cube(60, 168, 14, PAL["ink"]))


def illu_missing():
    dx = 46 * C30
    return svg(W, H, shadow(160, 210, 108, 20)
               + cube(160, 120, 46, PAL["sand"])
               + cube(160 + dx, 120 + 23, 46, PAL["sage"])
               + cube_outline(160 - dx, 120 + 23, 46, CORAL, 3.5)
               + f'<path d="M{160 - dx - 9:.0f} {143} h18 M{160 - dx:.0f} {134} v18" stroke="{CORAL}" stroke-width="5" stroke-linecap="round"/>'
               + spark(250, 66, 12, CORAL, 0.8) + cube(64, 172, 16, PAL["sky"]))


def illu_conflict():
    bolt = ('<path d="M160 70 L146 118 L166 118 L152 168" stroke="#D97757" stroke-width="9" fill="none" '
            'stroke-linecap="round" stroke-linejoin="round"/>')
    return svg(W, H, shadow(160, 208, 118, 20)
               + cube(86, 136, 46, PAL["coral"]) + cube(234, 136, 46, PAL["sky"])
               + bolt + spark(186, 84, 10, CORAL, 0.8) + spark(124, 174, 8, CORAL, 0.7)
               + cube(160, 196, 14, PAL["ink"]))


def illu_server():
    def slab(y, led):
        return (box(160, y, 96, 26, PAL["ink"], rounding=0.07)
                + f'<circle cx="{160 + 46 * C30 - 12:.0f}" cy="{y + 14 + 24 * 0.0:.0f}" r="0" />'
                + "".join(f'<circle cx="{190 + 12 * i}" cy="{y + 45 - i * 6.9:.0f}" r="3.6" fill="{c}"/>'
                          for i, c in enumerate(led))
                + f'<path d="M{160 - 56:.0f} {y + 12} L{160 - 18:.0f} {y + 31} M{160 - 56:.0f} {y + 22} L{160 - 18:.0f} {y + 41}" '
                  f'stroke="#fff" stroke-opacity="0.16" stroke-width="3" stroke-linecap="round"/>')
    body = shadow(160, 214, 104, 20)
    body += slab(160, ["#92AB83", CORAL]) + slab(122, ["#92AB83", "#92AB83"]) + slab(84, [CORAL, "#92AB83"])
    body += spark(250, 72, 12, CORAL, 0.8) + cube(256, 170, 16, PAL["sand"])
    return svg(W, H, body)


def illu_logs():
    doc = ('<g><rect x="104" y="46" width="124" height="152" rx="14" fill="#FAF9F5" stroke="#D9D3C2" stroke-width="2.5"/>'
           + "".join(f'<rect x="122" y="{74 + i * 20}" width="{w}" height="7" rx="3.5" fill="{c}"/>'
                     for i, (w, c) in enumerate([(70, "#D8D2C2"), (88, "#D8D2C2"), (52, "#D97757"), (80, "#D8D2C2"), (60, "#D8D2C2")]))
           + "</g>")
    mag = ('<g><circle cx="226" cy="168" r="26" fill="#FAF9F5" fill-opacity="0.85" stroke="#4C4A44" stroke-width="7"/>'
           '<path d="M245 187 L268 210" stroke="#4C4A44" stroke-width="9" stroke-linecap="round"/></g>')
    return svg(W, H, shadow(166, 214, 100, 18) + cube(70, 150, 20, PAL["coral"]) + doc + mag + spark(86, 84, 11, CORAL, 0.8))


def illu_welcome():
    """Dossier + cubes — écran d'accueil / état vide."""
    folder = (f'<path d="M62 92 q0 -14 14 -14 h54 q8 0 13 6 l8 10 h92 q14 0 14 14 v78 q0 14 -14 14 h-167 q-14 0 -14 -14 Z" fill="#E3D6B6"/>'
              f'<path d="M52 112 q0 -14 14 -14 h188 q14 0 14 14 v74 q0 14 -14 14 h-188 q-14 0 -14 -14 Z" fill="#F0E6CF"/>')
    return svg(W, H, shadow(160, 214, 112, 20) + folder
               + cube(120, 98, 32, PAL["coral"]) + cube(176, 84, 28, PAL["sage"]) + cube(224, 100, 24, PAL["sky"])
               + spark(264, 60, 11, CORAL, 0.8))


# ----------------------------------------------------------------------------

def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def render_png(svg_path, png_path, width=None, height=None, bg=None):
    exe = shutil.which("rsvg-convert")
    if not exe:
        return False
    cmd = [exe, svg_path, "-o", png_path]
    if width:
        cmd += ["-w", str(width)]
    if height:
        cmd += ["-h", str(height)]
    if bg:
        cmd += ["-b", bg]
    subprocess.run(cmd, check=True)
    return True


def main():
    write(os.path.join(OUT, "logo.svg"), logo_icon())
    write(os.path.join(OUT, "logo-mark.svg"), logo_mark())
    write(os.path.join(OUT, "logo-lockup.svg"), logo_lockup())
    write(os.path.join(OUT, "hero.svg"), hero_svg())
    write(os.path.join(OUT, "banner.svg"), banner_svg())
    for name, fn in [("ok", illu_ok), ("duplicates", illu_duplicates), ("missing", illu_missing),
                     ("conflict", illu_conflict), ("server", illu_server), ("logs", illu_logs),
                     ("welcome", illu_welcome)]:
        write(os.path.join(ILLU, f"{name}.svg"), fn())

    ok = True
    for size in (512, 256, 128, 64, 32, 16):
        ok &= render_png(os.path.join(OUT, "logo.svg"), os.path.join(OUT, f"logo-{size}.png"), size, size)
    ok &= render_png(os.path.join(OUT, "logo.svg"), os.path.join(OUT, "apple-touch-icon.png"), 180, 180)
    ok &= render_png(os.path.join(OUT, "banner.svg"), os.path.join(OUT, "banner.png"), 1280, 640)
    ok &= render_png(os.path.join(OUT, "hero.svg"), os.path.join(OUT, "hero.png"), 1440)
    if not ok:
        print("rsvg-convert introuvable : seuls les SVG ont été générés.")
        return
    try:
        from PIL import Image
        img = Image.open(os.path.join(OUT, "logo-256.png"))
        img.save(os.path.join(OUT, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    except ImportError:
        print("Pillow absent : favicon.ico non généré.")
    print("Assets écrits dans", OUT)


if __name__ == "__main__":
    sys.exit(main())
