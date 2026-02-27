from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


# ----------------------------
# ID <-> RGB
# ----------------------------
def id_to_rgb(i: int) -> tuple[int, int, int]:
    if i < 0 or i > 0xFFFFFF:
        raise ValueError("Province id must be within 0..16777215 (24-bit).")
    return (i >> 16) & 255, (i >> 8) & 255, i & 255


def parse_rgb(s: str) -> tuple[int, int, int]:
    """
    Accepts '#RRGGBB' / 'RRGGBB' / 'r,g,b'
    """
    s = s.strip()
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) != 3:
            raise argparse.ArgumentTypeError("RGB must be 'r,g,b'.")
        try:
            r, g, b = (int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError as e:
            raise argparse.ArgumentTypeError("RGB values must be integers.") from e
        for v in (r, g, b):
            if v < 0 or v > 255:
                raise argparse.ArgumentTypeError("RGB values must be in 0..255.")
        return (r, g, b)

    if s.startswith("#"):
        s = s[1:]
    if len(s) != 6:
        raise argparse.ArgumentTypeError("Hex color must be 6 chars like #303030.")
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except ValueError as e:
        raise argparse.ArgumentTypeError("Invalid hex color.") from e
    return (r, g, b)


def color_match_rgb(rgb: np.ndarray, color: tuple[int, int, int], tol: int) -> np.ndarray:
    """
    rgb: uint8 [H,W,3]
    returns bool [H,W] where pixel is within tolerance per channel.
    """
    if tol <= 0:
        return (rgb[..., 0] == color[0]) & (rgb[..., 1] == color[1]) & (rgb[..., 2] == color[2])

    a = rgb.astype(np.int16)
    c = np.array(color, dtype=np.int16)
    diff = np.abs(a - c)
    return (diff[..., 0] <= tol) & (diff[..., 1] <= tol) & (diff[..., 2] <= tol)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Mask -> province_id.png + provinces.json (fast OpenCV LUT version)")
    p.add_argument("-i", "--input", default="mask.png", help="Input mask (PNG).")
    p.add_argument("--out-img", default="province_id.png", help="Output province id PNG.")
    p.add_argument("--out-json", default="provinces.json", help="Output JSON metadata.")

    # Mask colors
    p.add_argument("--border", type=parse_rgb, default="#000000", help="Border color in mask.")
    p.add_argument("--land", type=parse_rgb, default="#ffffff", help="Land color in mask.")
    p.add_argument("--water", type=parse_rgb, default="#303030", help="Water color in mask.")

    # Output colors for non-province pixels
    p.add_argument("--out-border", type=parse_rgb, default="#000000", help="Border color in output.")
    p.add_argument("--out-water", type=parse_rgb, default="#303030", help="Water color in output.")

    # Tolerance and morphology
    p.add_argument("--tol", type=int, default=0, help="Per-channel tolerance for color matching (0=exact).")
    p.add_argument("--dilate-borders-1px", action="store_true", help="Dilate borders by 1px (3x3).")

    # Province filtering
    p.add_argument("--min-area", type=int, default=1, help="Minimum province area in px (filter blobs).")
    p.add_argument("--connectivity", type=int, choices=(4, 8), default=4, help="Connected components connectivity.")

    # Output formatting
    p.add_argument("--pretty-json", action="store_true", help="Pretty JSON (indent=2). Bigger + slower.")
    p.add_argument("--png-compress", type=int, default=1,
                   help="PNG compress_level for Pillow 0..9 (lower=faster, bigger file). Default 1.")
    return p


def main() -> int:
    args = build_argparser().parse_args()

    t0 = time.perf_counter()

    inp = Path(args.input)
    if not inp.exists():
        raise FileNotFoundError(f"Input not found: {inp}")

    # Read with OpenCV (BGR) then convert to RGB for color matching
    bgr = cv2.imread(str(inp), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError("cv2.imread failed to read the image.")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    h, w = rgb.shape[:2]

    # Build masks by exact color (with tolerance)
    border = color_match_rgb(rgb, args.border, args.tol).astype(np.uint8)
    land = color_match_rgb(rgb, args.land, args.tol).astype(np.uint8)
    water = color_match_rgb(rgb, args.water, args.tol).astype(np.uint8)

    # Resolve overlaps by priority: border > land > water
    land = land & (1 - border)
    water = water & (1 - border) & (1 - land)

    if args.dilate_borders_1px:
        kernel = np.ones((3, 3), np.uint8)
        border = cv2.dilate(border, kernel, iterations=1)
        land = land & (1 - border)
        water = water & (1 - border) & (1 - land)

    # Components only on land-not-border
    fillmask = (land & (1 - border)).astype(np.uint8)

    # connected components
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        fillmask, connectivity=args.connectivity
    )
    areas = stats[:, cv2.CC_STAT_AREA].astype(np.int32)

    t_cc = time.perf_counter()

    # ----------------------------
    # FAST COLORING: LUT approach
    # ----------------------------
    lut = np.zeros((num_labels, 3), dtype=np.uint8)

    # Background label 0: water output color (or black if you want)
    lut[0] = np.array(args.out_water, dtype=np.uint8)

    # Labels 1..N-1: province colors (or water if filtered)
    min_area = int(args.min_area)
    for lab in range(1, num_labels):
        if int(areas[lab]) < min_area:
            lut[lab] = np.array(args.out_water, dtype=np.uint8)
        else:
            lut[lab] = np.array(id_to_rgb(lab), dtype=np.uint8)

    # One-shot paint
    out = lut[labels]  # [H,W,3]

    # Preserve water pixels from original mask (so water stays water even if background areas exist)
    # This matters if there are "unknown" pixels not classified as land/border/water.
    out[water.astype(bool)] = args.out_water

    # Borders always override
    out[border.astype(bool)] = args.out_border

    t_paint = time.perf_counter()

    # ----------------------------
    # Build JSON metadata (fast)
    # ----------------------------
    provinces = []
    provinces_reserve = max(0, num_labels - 1)
    provinces = []
    provinces_append = provinces.append

    for lab in range(1, num_labels):
        area = int(areas[lab])
        if area < min_area:
            continue
        r, g, b = map(int, lut[lab])
        cx, cy = centroids[lab]  # floats
        provinces_append({
            "id": int(lab),
            "color": "#{:02x}{:02x}{:02x}".format(r, g, b),
            "area_px": area,
            "center_px": {"x": float(cx), "y": float(cy)}
        })

    prov_areas = [p["area_px"] for p in provinces]
    meta = {
        "source": str(inp),
        "size": {"w": int(w), "h": int(h)},
        "provinces_count": int(len(provinces)),
        "min_area_px": int(min(prov_areas)) if prov_areas else 0,
        "max_area_px": int(max(prov_areas)) if prov_areas else 0,
        "connectivity": int(args.connectivity),
        "min_area_filter": int(min_area),
        "dilate_borders_1px": bool(args.dilate_borders_1px),
        "tolerance": int(args.tol),
        "mask_colors": {
            "border": "#{:02x}{:02x}{:02x}".format(*args.border),
            "land": "#{:02x}{:02x}{:02x}".format(*args.land),
            "water": "#{:02x}{:02x}{:02x}".format(*args.water),
        },
        "output_colors": {
            "border": "#{:02x}{:02x}{:02x}".format(*args.out_border),
            "water": "#{:02x}{:02x}{:02x}".format(*args.out_water),
        },
        "id_encoding": "id=(r<<16)|(g<<8)|b; r,g,b from province_id.png",
    }

    t_json = time.perf_counter()

    # ----------------------------
    # Save outputs
    # ----------------------------
    out_img_path = Path(args.out_img)
    out_json_path = Path(args.out_json)

    # Pillow fast PNG settings
    Image.fromarray(out).save(out_img_path, format="PNG", optimize=False, compress_level=int(args.png_compress))

    payload = {"meta": meta, "provinces": provinces}
    if args.pretty_json:
        out_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        out_json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    t_save = time.perf_counter()

    # ----------------------------
    # Print timings
    # ----------------------------
    print("Done!")
    print(f"Size: {w}x{h}")
    print(f"Labels (incl background): {num_labels}")
    print(f"Provinces (after min-area): {meta['provinces_count']}")
    print(f"Min area: {meta['min_area_px']} px | Max area: {meta['max_area_px']} px")
    print(f"Outputs: {out_img_path}, {out_json_path}")
    print()
    print("Timings:")
    print(f"  ConnectedComponents: {t_cc - t0:.3f}s")
    print(f"  Paint (LUT):         {t_paint - t_cc:.3f}s")
    print(f"  Build JSON:          {t_json - t_paint:.3f}s")
    print(f"  Save files:          {t_save - t_json:.3f}s")
    print(f"  TOTAL:               {t_save - t0:.3f}s")
    # ----------------------------
    # Top-10 debug
    # ----------------------------
    top_10 = sorted(provinces, key=lambda p: p["area_px"], reverse=True)[:10]
    print("\n--- TOP 10 PROVINCES BY AREA ---")
    for i, p in enumerate(top_10, 1):
        print(f"{i:>2}. ID: {p['id']:<6} | Area: {p['area_px']:>8} px | Center: ({int(p['center_px']['x'])}, {int(p['center_px']['y'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())