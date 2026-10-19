# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy"]
# ///
"""Chibi rig starter files: a layered PSD template and a proportion guide.

The PSD has every layer from docs/rig-checklist.md, empty, named and in draw
order (back to front), plus a `_guide` group on top and a `_paper` layer at the
bottom; delete both before importing into Cubism. The guide PNG shows the
front and 3/4 construction, nine expression blanks and her palette.

    uv run tools/make_rig_template.py [--out D:/Projects/Chibi-Agent-Project/ChibiAgent/art/chibi]

Output is art, so it goes outside the repo.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 1600  # PSD canvas (docs/rig-checklist.md -> Budget)

# Front construction, canvas px. One head (skull top to chin) = 520 px; 2.5 heads.
CX = 600
Y = {
    "hair dome": 140, "skull top": 200, "eye line": 530, "chin": 720,
    "shoulders": 760, "hips": 1080, "knees": 1290, "ground": 1500,
}
HEAD_R, HEAD_CY = 250, 450

INK = (43, 47, 58)
GUIDE = (62, 143, 214)
SOFT = (168, 221, 245)
HALO = (216, 180, 90)

PALETTE = [  # docs/character.md -> Visual design
    ("hair light", "#A8DDF5"), ("hair mid", "#6CC0EC"), ("hair shadow", "#3E8FD6"),
    ("eyes ruby", "#D4243A"), ("eye rim", "#8E1426"), ("skin", "#FBE6DA"),
    ("white", "#FAFBFF"), ("cloth shadow", "#C8D0E4"), ("gold", "#D8B45A"),
    ("halo gems", "#C8372D"), ("cyan glow", "#7FE3FF"), ("ink outline", "#2B2F3A"),
]
EXPRESSIONS = ["neutral", "happy", "surprised", "pout", "upset",
               "sleepy", "thinking", "focused", "warning"]


def eye_pair(side: str) -> list[str]:
    return [f"eye_{side}_{p}" for p in ("white", "iris", "highlight", "lid", "lash_upper",
                                        "lash_lower", "blank")] + [f"tear_{side}"]


# Draw order, back to front (docs/rig-checklist.md -> PSD layers).
GROUPS: list[tuple[str, list]] = [
    ("halo", ["halo_glow", "halo_ring", "halo_spikes", "halo_gems"]),
    ("back", ["hood_back", "hair_back", "sleeve_R_back"]),
    ("body", ["leg_L", "leg_R", "foot_L", "foot_R", "robe_skirt", "robe_tail", "torso",
              "shoulder_bare", "robe_body", "robe_drape", "neck", "neck_shadow"]),
    ("arms", ["arm_L", "arm_R", "sleeve_L", "sleeve_R", "hand_L", "hand_R", "hand_R_chin",
              "hand_L_analyse", "hand_R_analyse"]),
    ("head", ["face", "face_shadow", "ear_L", "ear_R", "nose", "blush",
              ("eye_L", eye_pair("L")), ("eye_R", eye_pair("R")),
              ("brows", ["brow_L", "brow_R"]),
              ("mouth", ["mouth_inner", "mouth_upper", "mouth_lower"])]),
    ("orb", ["orb_glow", "orb_core", "orb_sparks"]),
    ("hair_front", ["hair_side_L", "hair_side_R", "hair_strand_L", "hair_strand_R",
                    "hair_front_1", "hair_front_2", "hair_front_3", "hair_front_4", "hair_shine"]),
    ("hood_front", ["hood_rim", "hood_fold"]),
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in (("arialbd.ttf" if bold else "arial.ttf"), "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def dashed_ellipse(d: ImageDraw.ImageDraw, box, color, width=3, dash=10):
    for a in range(0, 360, dash * 2 // 2):
        if (a // dash) % 2 == 0:
            d.arc(box, a, a + dash, fill=color, width=width)


def draw_front(d: ImageDraw.ImageDraw, ox: int, labels: bool = True) -> None:
    """Front construction with its left edge at ox (the PSD uses ox = 0)."""
    cx = ox + CX
    f = font(22)
    # level lines
    for name, y in Y.items():
        d.line([(ox + 150, y), (ox + 1050, y)], fill=SOFT, width=2)
        if labels:
            d.text((ox + 1058, y - 12), name, fill=GUIDE, font=f)
    # head-unit ruler: skull top -> ground in 520 px steps
    rx = ox + 110
    for i, y in enumerate((200, 720, 1240)):
        d.line([(rx, y), (rx, min(y + 520, 1500))], fill=GUIDE if i % 2 == 0 else INK, width=6)
    for label, y in (("1", 450), ("2", 970), ("2.5", 1360)):
        d.text((rx - 60, y), label, fill=GUIDE, font=f)
    # halo, hair dome, side locks (dashed: volume, not lines to ink)
    dashed_ellipse(d, (cx - 360, 420 - 360, cx + 360, 420 + 360), HALO, 3)
    dashed_ellipse(d, (cx - 300, 140, cx + 300, 760), GUIDE, 3)
    for sx in (-1, 1):
        d.line([(cx + sx * 290, 520), (cx + sx * 250, 1420)], fill=SOFT, width=3)
    # skull and jaw
    d.ellipse((cx - HEAD_R, HEAD_CY - HEAD_R, cx + HEAD_R, HEAD_CY + HEAD_R), outline=INK, width=4)
    d.line([(cx - 235, 540), (cx - 120, 690), (cx, 720), (cx + 120, 690), (cx + 235, 540)], fill=INK, width=4)
    d.line([(cx, 200), (cx, 720)], fill=GUIDE, width=2)  # centre line
    # face: big eyes set low, tiny nose and mouth, ears on the eye line
    for sx in (-1, 1):
        ex = cx + sx * 125
        d.rounded_rectangle((ex - 62, 465, ex + 62, 605), 40, outline=INK, width=3)
        d.ellipse((ex - 38, 495, ex + 38, 600), outline=(212, 36, 58), width=3)
        d.ellipse((cx + sx * 238 - 18, 510, cx + sx * 238 + 18, 580), outline=INK, width=3)
        d.ellipse((ex - 55 + sx * 10, 610, ex + 25 + sx * 10, 645), outline=(240, 160, 170), width=2)  # blush
    d.line([(cx - 4, 615), (cx + 4, 615)], fill=INK, width=3)
    d.line([(cx - 18, 660), (cx + 18, 660)], fill=INK, width=3)
    # body: 1.5 heads, short neck, narrow shoulders, stubby limbs
    d.rectangle((cx - 40, 712, cx + 40, 760), outline=INK, width=3)
    d.polygon([(cx - 170, 760), (cx + 170, 760), (cx + 150, 1080), (cx - 150, 1080)], outline=INK, width=4)
    for sx in (-1, 1):
        d.line([(cx + sx * 165, 775), (cx + sx * 235, 1040)], fill=INK, width=4)  # arm
        d.ellipse((cx + sx * 235 - 35, 1030, cx + sx * 235 + 35, 1100), outline=INK, width=3)  # hand
        lx = cx + sx * 70
        d.rectangle((lx - 45, 1080, lx + 45, 1450), outline=INK, width=3)  # leg
        d.ellipse((lx - 55 + sx * 10, 1440, lx + 55 + sx * 10, 1505), outline=INK, width=3)  # bare foot
    # orb in front of the chest (analyse)
    d.ellipse((cx - 75, 860, cx + 75, 1010), outline=(127, 227, 255), width=4)
    if labels:
        g = font(20)
        d.text((cx + 120, 98), "hair dome / hood volume", fill=GUIDE, font=g)
        d.text((cx + 330, 330), "halo", fill=HALO, font=g)
        d.text((cx + 90, 920), "orb (analyse)", fill=(60, 170, 210), font=g)
        d.text((cx - 140, 1520), "front  ·  2.5 heads  ·  head 520 px", fill=INK, font=font(24, True))


def draw_three_quarter(d: ImageDraw.ImageDraw, ox: int) -> None:
    """3/4 view, turned to her right (our left): centre line and far eye squeeze."""
    cx = ox + CX
    f = font(22)
    for name, y in Y.items():
        d.line([(ox + 150, y), (ox + 1050, y)], fill=SOFT, width=2)
    dashed_ellipse(d, (cx - 360, 60, cx + 360, 780), HALO, 3)
    dashed_ellipse(d, (cx - 300, 140, cx + 300, 760), GUIDE, 3)
    d.ellipse((cx - HEAD_R, HEAD_CY - HEAD_R, cx + HEAD_R, HEAD_CY + HEAD_R), outline=INK, width=4)
    # centre line: a vertical ellipse arc, about 0.4 r toward her right
    d.arc((cx - 95, 200, cx + 5, 700), 90, 270, fill=GUIDE, width=3)
    d.line([(cx - 248, 530), (cx - 185, 670), (cx - 60, 720), (cx + 90, 690), (cx + 235, 540)], fill=INK, width=4)
    # far eye narrow, between the far edge and the centre line; near eye full
    d.rounded_rectangle((cx - 215, 470, cx - 135, 600), 30, outline=INK, width=3)
    d.rounded_rectangle((cx - 45, 465, cx + 85, 605), 40, outline=INK, width=3)
    d.ellipse((cx - 172, 495, cx - 140, 595), outline=(212, 36, 58), width=3)
    d.ellipse((cx - 15, 495, cx + 60, 600), outline=(212, 36, 58), width=3)
    d.ellipse((cx + 170, 510, cx + 210, 580), outline=INK, width=3)  # near ear
    d.line([(cx - 98, 612), (cx - 90, 618)], fill=INK, width=3)  # nose on the centre line
    d.line([(cx - 85, 662), (cx - 55, 662)], fill=INK, width=3)
    # body turned: torso narrower, centre line offset
    d.rectangle((cx - 70, 712, cx + 10, 760), outline=INK, width=3)
    d.polygon([(cx - 150, 760), (cx + 140, 760), (cx + 125, 1080), (cx - 135, 1080)], outline=INK, width=4)
    d.line([(cx - 50, 760), (cx - 40, 1080)], fill=GUIDE, width=2)
    d.line([(cx + 140, 775), (cx + 215, 1040)], fill=INK, width=4)
    d.line([(cx - 150, 775), (cx - 190, 1030)], fill=INK, width=4)
    d.ellipse((cx + 185, 1030, cx + 250, 1100), outline=INK, width=3)
    d.ellipse((cx - 220, 1020, cx - 160, 1085), outline=INK, width=3)
    for lx in (cx - 80, cx + 50):
        d.rectangle((lx - 42, 1080, lx + 42, 1450), outline=INK, width=3)
        d.ellipse((lx - 70, 1440, lx + 40, 1505), outline=INK, width=3)
    d.text((cx - 150, 1520), "3/4  ·  turned to her right", fill=INK, font=font(24, True))


def guide_sheet() -> Image.Image:
    sheet = Image.new("RGB", (2900, 2260), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    d.text((60, 30), "Raphael · chibi proportion guide (white robe)", fill=INK, font=font(40, True))
    draw_front(d, 0)
    draw_three_quarter(d, 1150)
    # expression blanks
    d.text((60, 1640), "Expressions (docs/character.md -> Required coverage)", fill=INK, font=font(30, True))
    for i, name in enumerate(EXPRESSIONS):
        x, y = 160 + i * 300, 1900
        d.ellipse((x - 120, y - 120, x + 120, y + 120), outline=INK, width=3)
        d.line([(x - 112, y + 40), (x - 60, y + 110), (x, y + 130), (x + 60, y + 110), (x + 112, y + 40)], fill=INK, width=3)
        d.line([(x, y - 120), (x, y + 130)], fill=SOFT, width=2)
        d.line([(x - 120, y + 30), (x + 120, y + 30)], fill=SOFT, width=2)  # eye line, low
        d.text((x - 60, y + 160), name, fill=INK, font=font(26))
    d.text((60, 2170), "Dashed shapes are volume (hair dome, hood, halo), not ink lines. "
           "Eyes sit low: the eye line is ~60 % down the head.", fill=GUIDE, font=font(24))
    # palette
    px = 2400
    d.text((px, 120), "Palette", fill=INK, font=font(30, True))
    for i, (name, hx) in enumerate(PALETTE):
        y = 180 + i * 105
        d.rectangle((px, y, px + 110, y + 80), fill=hx, outline=INK, width=2)
        d.text((px + 125, y + 8), name, fill=INK, font=font(24))
        d.text((px + 125, y + 42), hx, fill=GUIDE, font=font(22))
    return sheet


# --- minimal PSD writer (RGB, 8-bit, raw channels; empty layers store no pixels) ---------
# Records go bottom to top; a group is a "</Layer group>" divider, its children,
# then the folder record that carries the group's name.

def _block(key: bytes, data: bytes) -> bytes:
    if len(data) % 2:
        data += b"\0"
    return b"8BIM" + key + struct.pack(">I", len(data)) + data


def _record(name: str, rect, img: np.ndarray | None, *, hidden=False, opacity=255,
            folder: int = 0, blend=b"norm") -> tuple[bytes, bytes]:
    """One layer record and its channel data. folder: 0 none, 1 open, 2 closed, 3 divider."""
    top, left, bottom, right = rect
    planes = [img[..., i] for i in (3, 0, 1, 2)] if img is not None else [None] * 4
    data = b"".join(struct.pack(">H", 0) + (p.tobytes() if p is not None else b"") for p in planes)
    lens = [2 + (p.size if p is not None else 0) for p in planes]
    head = struct.pack(">iiiiH", top, left, bottom, right, 4)
    head += b"".join(struct.pack(">hI", cid, n) for cid, n in zip((-1, 0, 1, 2), lens))
    head += b"8BIM" + blend + struct.pack(">BBBB", opacity, 0, 2 if hidden else 0, 0)
    raw = name.encode("ascii", "replace")[:255]
    pas = bytes([len(raw)]) + raw
    pas += b"\0" * (-len(pas) % 4)
    extra = struct.pack(">II", 0, 0) + pas
    extra += _block(b"luni", struct.pack(">I", len(name)) + name.encode("utf-16-be"))
    if folder:
        extra += _block(b"lsct", struct.pack(">I", folder) + (b"8BIM" + blend if folder != 3 else b""))
    head += struct.pack(">I", len(extra)) + extra
    return head, data


def _layers(items: list, out: list) -> None:
    """Append records for a back-to-front list of names / (group, items)."""
    for it in items:
        if isinstance(it, tuple):
            name, children = it
            out.append(_record("</Layer group>", (0, 0, 0, 0), None, folder=3))
            _layers(children, out)
            out.append(_record(name, (0, 0, 0, 0), None, folder=1, blend=b"pass"))
        else:
            out.append(_record(it, (0, 0, 0, 0), None))


def build_psd(out: Path) -> None:
    guide_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_front(ImageDraw.Draw(guide_img), 0)
    guide = np.asarray(guide_img)
    paper = np.full((H, W, 4), 255, np.uint8)
    recs = [_record("_paper (delete before Cubism)", (0, 0, H, W), paper)]
    _layers(GROUPS, recs)
    recs.append(_record("</Layer group>", (0, 0, 0, 0), None, folder=3))
    recs.append(_record("proportions", (0, 0, H, W), guide, opacity=150))
    recs.append(_record("_guide (delete before Cubism)", (0, 0, 0, 0), None, folder=2, blend=b"pass"))

    info = struct.pack(">h", len(recs)) + b"".join(r for r, _ in recs) + b"".join(d for _, d in recs)
    info += b"\0" * (-len(info) % 4)
    lmi = struct.pack(">I", len(info)) + info + struct.pack(">I", 0)
    faded = guide_img.copy()
    faded.putalpha(guide_img.getchannel("A").point(lambda a: a * 150 // 255))
    m = np.asarray(Image.alpha_composite(Image.fromarray(paper), faded))
    with open(out, "wb") as fd:
        fd.write(b"8BPS" + struct.pack(">H6xHIIHH", 1, 4, H, W, 8, 3))
        fd.write(struct.pack(">II", 0, 0))  # colour mode data, image resources
        fd.write(struct.pack(">I", len(lmi)) + lmi)
        fd.write(struct.pack(">H", 0) + b"".join(m[..., i].tobytes() for i in (0, 1, 2, 3)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("D:/Projects/Chibi-Agent-Project/ChibiAgent/art/chibi"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    build_psd(a.out / "raphael_chibi_robe_template.psd")
    guide_sheet().save(a.out / "proportion_guide.png")
    print(f"wrote {a.out / 'raphael_chibi_robe_template.psd'} and {a.out / 'proportion_guide.png'}")


if __name__ == "__main__":
    main()
