"""Render reviewed image cells as aligned 800x800 PNGs without altering labels."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


SIZE = 800
DEFAULTS = {
    "alignment": "number",
    "content_width": 660,
    "number_center_x": 400,
    "number_bottom": 590,
    "margin": 32,
    "ink_threshold": 160,
    "background_threshold": 248,
}


@dataclass
class Item:
    filename: str
    cell_box: tuple[int, int, int, int]
    content_box: tuple[int, int, int, int]
    number_box: tuple[int, int, int, int] | None
    image: Image.Image
    alignment: str


def load_image(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        upright = ImageOps.exif_transpose(opened)
        if "A" in upright.getbands() or "transparency" in upright.info:
            rgba = upright.convert("RGBA")
            canvas = Image.new("RGBA", rgba.size, "white")
            return Image.alpha_composite(canvas, rgba).convert("RGB")
        return upright.convert("RGB")


def check_box(value, size, label):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{label}: expected [left, top, right, bottom]")
    if any(type(n) is not int for n in value):
        raise ValueError(f"{label}: coordinates must be integers")
    left, top, right, bottom = value
    if not (0 <= left < right <= size[0] and 0 <= top < bottom <= size[1]):
        raise ValueError(f"{label}: box {value} is outside image {size}")
    return tuple(value)


def contains(outer, inner):
    return (outer[0] <= inner[0] < inner[2] <= outer[2]
            and outer[1] <= inner[1] < inner[3] <= outer[3])


def offset_box(box, x, y):
    return box[0] + x, box[1] + y, box[2] + x, box[3] + y


def ink_bounds(image, threshold):
    ys, xs = np.nonzero(np.max(np.asarray(image), axis=2) < threshold)
    if not len(xs):
        raise ValueError("No dark label pixels found; review number_box/number_region")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def find_number(image, region, threshold):
    """Find a candidate text line; this deliberately does not claim to OCR it."""
    crop = image.crop(region)
    mask = (np.max(np.asarray(crop), axis=2) < threshold).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    width, height = image.size
    candidates = []
    for x, y, w, h, area in stats[1:]:
        if (area >= max(3, width * height * 0.00012)
                and max(5, height * 0.04) <= h <= height * 0.22
                and 1 <= w <= width * 0.2):
            candidates.append(tuple(map(int, (x, y, w, h))))
    groups = []
    for component in sorted(candidates, key=lambda b: b[1] + b[3] / 2):
        center = component[1] + component[3] / 2
        for group in groups:
            group_center = sum(b[1] + b[3] / 2 for b in group) / len(group)
            if abs(center - group_center) <= max(2, component[3] * 0.4):
                group.append(component)
                break
        else:
            groups.append([component])
    boxes = []
    for group in groups:
        box = (min(b[0] for b in group), min(b[1] for b in group),
               max(b[0] + b[2] for b in group), max(b[1] + b[3] for b in group))
        if (box[2] - box[0] <= width * 0.55
                and box[2] - box[0] <= 6 * (box[3] - box[1])):
            boxes.append(box)
    if not boxes:
        raise ValueError("Cannot locate a label; inspect the cell and supply number_box")
    return offset_box(min(boxes, key=lambda b: b[1]), region[0], region[1])


def trim_bounds(image, threshold):
    mask = (np.min(np.asarray(image), axis=2) < threshold).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    usable = [b for b in stats[1:] if b[4] >= 4]
    if not usable:
        raise ValueError("No visible content found; review box or disable trim for pale content")
    padding = 4
    return (max(0, min(int(b[0]) for b in usable) - padding),
            max(0, min(int(b[1]) for b in usable) - padding),
            min(image.width, max(int(b[0] + b[2]) for b in usable) + padding),
            min(image.height, max(int(b[1] + b[3]) for b in usable) + padding))


def grid_boxes(grid, size):
    edges = []
    for key, maximum in (("x_edges", size[0]), ("y_edges", size[1])):
        values = grid.get(key)
        if (not isinstance(values, list) or len(values) < 2
                or any(type(n) is not int for n in values)
                or values[0] < 0 or values[-1] > maximum
                or any(a >= b for a, b in zip(values, values[1:]))):
            raise ValueError(f"grid.{key}: expected increasing in-image integer edges")
        edges.append(values)
    xs, ys = edges
    counts = grid.get("row_counts", [len(xs) - 1] * (len(ys) - 1))
    if (not isinstance(counts, list) or len(counts) != len(ys) - 1
            or any(type(n) is not int or not 0 <= n < len(xs) for n in counts)):
        raise ValueError("grid.row_counts: supply one valid item count per row")
    return [(xs[c], ys[r], xs[c + 1], ys[r + 1])
            for r, count in enumerate(counts) for c in range(count)]


def options_for(plan):
    supplied = plan.get("options", {})
    if not isinstance(supplied, dict) or set(supplied) - set(DEFAULTS):
        raise ValueError("Unknown options; see references/layout.md")
    options = {**DEFAULTS, **supplied}
    if options["alignment"] not in ("number", "content"):
        raise ValueError("alignment must be number or content")
    for key in set(DEFAULTS) - {"alignment"}:
        if type(options[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    if not 0 <= options["margin"] < SIZE / 2:
        raise ValueError("margin must be between 0 and 399")
    if not 1 <= options["content_width"] <= SIZE:
        raise ValueError("content_width must be between 1 and 800")
    for key in ("number_center_x", "number_bottom"):
        if not options["margin"] < options[key] < SIZE - options["margin"]:
            raise ValueError(f"{key} must be inside the canvas safety margins")
    for key in ("ink_threshold", "background_threshold"):
        if not 1 <= options[key] <= 255:
            raise ValueError(f"{key} must be between 1 and 255")
    return options


def prepare_items(source, plan, options):
    if plan.get("source_size") != list(source.size):
        raise ValueError(f"source_size must match the EXIF-oriented image: {list(source.size)}")
    specs = plan.get("items")
    if not isinstance(specs, list) or not specs:
        raise ValueError("items must be a nonempty list")
    cells = grid_boxes(plan["grid"], source.size) if "grid" in plan else None
    if cells is not None and len(cells) != len(specs):
        raise ValueError("items count does not match the populated grid cells")
    items = []
    for index, spec in enumerate(specs, 1):
        if not isinstance(spec, dict) or not isinstance(spec.get("color"), str) or not spec["color"].strip():
            raise ValueError(f"Item {index}: color is required")
        if set(spec) - {"color", "box", "number_box", "number_region", "trim", "alignment"}:
            raise ValueError(f"Item {index}: unknown field; see references/layout.md")
        color = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", spec["color"]).strip(" .")
        if not color or len(color) > 80:
            raise ValueError(f"Item {index}: color name must contain 1-80 filename-safe characters")
        cell_box = check_box(spec.get("box", cells[index - 1] if cells else None),
                             source.size, f"Item {index}")
        cell = source.crop(cell_box)
        alignment = spec.get("alignment", options["alignment"])
        if alignment not in ("number", "content"):
            raise ValueError(f"Item {index}: alignment must be number or content")
        if "trim" in spec and type(spec["trim"]) is not bool:
            raise ValueError(f"Item {index}: trim must be true or false")
        number = None
        if alignment == "number":
            key = "number_box" if "number_box" in spec else "number_region"
            if key in spec:
                region = check_box(spec[key], source.size, f"Item {index} {key}")
                if not contains(cell_box, region):
                    raise ValueError(f"Item {index}: {key} must be inside its cell")
                local_region = offset_box(region, -cell_box[0], -cell_box[1])
            else:
                local_region = (int(cell.width * 0.2), int(cell.height * 0.68),
                                max(1, int(cell.width * 0.8)), cell.height)
            try:
                if key == "number_box":
                    number = ink_bounds(cell.crop(local_region), options["ink_threshold"])
                    number = offset_box(number, local_region[0], local_region[1])
                else:
                    number = find_number(cell, local_region, options["ink_threshold"])
            except ValueError as error:
                raise ValueError(f"Item {index}: {error}") from error
        elif "number_box" in spec or "number_region" in spec:
            raise ValueError(f"Item {index}: content alignment must not specify a number box")
        trimmed = trim_bounds(cell, options["background_threshold"]) if spec.get("trim", True) else (0, 0, *cell.size)
        if number and not contains(trimmed, number):
            trimmed = (min(trimmed[0], number[0]), min(trimmed[1], number[1]),
                       max(trimmed[2], number[2]), max(trimmed[3], number[3]))
        items.append(Item(f"{index:02d}_{color}.png", cell_box,
                          offset_box(trimmed, cell_box[0], cell_box[1]),
                          offset_box(number, cell_box[0], cell_box[1]) if number else None,
                          cell.crop(trimmed), alignment))
    return items


def local_number(item):
    return offset_box(item.number_box, -item.content_box[0], -item.content_box[1])


def shared_scale(items, options):
    scale = options["content_width"] / max(item.image.width for item in items)
    margin = options["margin"] + 2  # Reserve space for integer rounding at resize.
    for item in items:
        if item.number_box:
            number = local_number(item)
            anchor_x, anchor_y = (number[0] + number[2]) / 2, number[3]
            target_x, target_y = options["number_center_x"], options["number_bottom"]
        else:
            anchor_x, anchor_y = item.image.width / 2, item.image.height / 2
            target_x = target_y = SIZE / 2
        for extent, room in ((anchor_x, target_x - margin),
                             (item.image.width - anchor_x, SIZE - margin - target_x),
                             (anchor_y, target_y - margin),
                             (item.image.height - anchor_y, SIZE - margin - target_y)):
            if extent > 0:
                scale = min(scale, room / extent)
    if scale <= 0:
        raise ValueError("Content cannot fit these anchors; review margin and number position")
    return scale


def load_edsr(path):
    if path is None:
        return None
    if not path.is_file():
        raise ValueError(f"EDSR model does not exist: {path}")
    if not hasattr(cv2, "dnn_superres"):
        raise ValueError("This OpenCV installation has no dnn_superres; omit --edsr-model")
    resolver = cv2.dnn_superres.DnnSuperResImpl_create()
    resolver.readModel(str(path))
    resolver.setModel("edsr", 4)
    return resolver


def compose(item, scale, options, resolver=None):
    image = item.image
    target_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    if resolver is not None:
        bgr = np.ascontiguousarray(np.asarray(image)[:, :, ::-1])
        image = Image.fromarray(resolver.upsample(bgr)[:, :, ::-1])
    resized = image.resize(target_size, Image.Resampling.LANCZOS)
    number = None
    if item.number_box:
        source_number = local_number(item)
        sx, sy = resized.width / item.image.width, resized.height / item.image.height
        region = (max(0, math.floor(source_number[0] * sx) - 3),
                  max(0, math.floor(source_number[1] * sy) - 3),
                  min(resized.width, math.ceil(source_number[2] * sx) + 3),
                  min(resized.height, math.ceil(source_number[3] * sy) + 3))
        number = ink_bounds(resized.crop(region), options["ink_threshold"])
        number = offset_box(number, region[0], region[1])
        x = round(options["number_center_x"] - (number[0] + number[2]) / 2)
        y = options["number_bottom"] - number[3]
    else:
        x, y = (SIZE - resized.width) // 2, (SIZE - resized.height) // 2
    if x < 0 or y < 0 or x + resized.width > SIZE or y + resized.height > SIZE:
        raise ValueError(f"{item.filename}: content would be clipped; review bounds and content_width")
    square = Image.new("RGB", (SIZE, SIZE), "white")
    square.paste(resized, (x, y))
    output_number = offset_box(number, x, y) if number else None
    if output_number:
        measured = ink_bounds(square.crop(output_number), options["ink_threshold"])
        measured = offset_box(measured, output_number[0], output_number[1])
        if (abs((measured[0] + measured[2]) / 2 - options["number_center_x"]) > 0.5
                or measured[3] != options["number_bottom"]):
            raise ValueError(f"{item.filename}: number anchor verification failed")
    return square, {"filename": item.filename, "cell_box": item.cell_box,
                    "content_box": item.content_box, "source_number_box": item.number_box,
                    "output_number_box": output_number, "alignment": item.alignment,
                    "paste_box": (x, y, x + resized.width, y + resized.height)}


def review_font(size):
    for candidate in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default()


def save_reviews(source, items, images, directory, report):
    directory.mkdir(parents=True, exist_ok=True)
    annotated = source.copy()
    draw = ImageDraw.Draw(annotated)
    line_width = max(1, round(source.width / 450))
    font = review_font(max(14, round(source.width / 60)))
    for index, item in enumerate(items, 1):
        for box, color in ((item.cell_box, "red"), (item.content_box, "#0075ff"),
                           (item.number_box, "#00a030")):
            if box:
                draw.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), outline=color, width=line_width)
        draw.text((item.cell_box[0] + 3, item.cell_box[1] + 3), str(index), fill="red", font=font,
                  stroke_width=1, stroke_fill="white")
    annotated.save(directory / "source-boxes.png", format="PNG")
    columns = min(5, len(images))
    tile_width, tile_height = 180, 206
    sheet = Image.new("RGB", (columns * tile_width, math.ceil(len(images) / columns) * tile_height), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    font = review_font(13)
    for index, (item, picture) in enumerate(zip(items, images)):
        x, y = index % columns * tile_width, index // columns * tile_height
        sheet.paste(picture.resize((176, 176), Image.Resampling.LANCZOS), (x + 2, y + 2))
        draw.text((x + 5, y + 180), item.filename, fill="#222222", font=font)
    sheet.save(directory / "contact-sheet.png", format="PNG")
    with (directory / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)


def run(mode, input_path, layout_path, output_path, edsr_model=None):
    input_path, layout_path, output_path = (Path(p).resolve() for p in (input_path, layout_path, output_path))
    archive_path = output_path.with_name(output_path.name + ".zip")
    if output_path.exists() or (mode == "render" and archive_path.exists()):
        raise ValueError("Output directory/ZIP already exists; choose a new name (nothing was overwritten)")
    with layout_path.open(encoding="utf-8-sig") as stream:
        plan = json.load(stream)
    if not isinstance(plan, dict) or set(plan) - {"source_size", "grid", "options", "items"}:
        raise ValueError("Invalid layout root; see references/layout.md")
    source = load_image(input_path)
    options = options_for(plan)
    items = prepare_items(source, plan, options)
    scale = shared_scale(items, options)
    resolver = load_edsr(Path(edsr_model).resolve()) if edsr_model else None
    if mode != "render" and resolver is not None:
        raise ValueError("EDSR is only supported for render, not preview")
    images, records = [], []
    for index, item in enumerate(items, 1):
        print(f"{mode}: {index}/{len(items)} {item.filename}", flush=True)
        picture, record = compose(item, scale, options, resolver)
        images.append(picture)
        records.append(record)
    output_path.mkdir(parents=True, exist_ok=False)
    report = {"source": str(input_path), "source_size": source.size, "mode": mode,
              "count": len(items), "output_size": [SIZE, SIZE], "format": "PNG", "color_mode": "RGB",
              "scale": scale, "upscaled": scale > 1,
              "enhancement": "edsr_x4" if resolver is not None else "lanczos",
              "options": options, "files_verified": False, "items": records}
    if mode == "render":
        for item, picture in zip(items, images):
            path = output_path / item.filename
            with path.open("xb") as stream:
                picture.save(stream, format="PNG", optimize=True)
            with Image.open(path) as check:
                check.load()
                if check.format != "PNG" or check.size != (SIZE, SIZE) or check.mode != "RGB":
                    raise ValueError(f"Output verification failed: {path}")
        if len(list(output_path.glob("*.png"))) != len(items):
            raise ValueError("PNG output count mismatch")
        with zipfile.ZipFile(archive_path, "x", zipfile.ZIP_DEFLATED) as archive:
            for item in items:
                archive.write(output_path / item.filename, arcname=item.filename)
        with zipfile.ZipFile(archive_path) as archive:
            if archive.namelist() != [item.filename for item in items] or archive.testzip() is not None:
                raise ValueError("ZIP verification failed")
        report["files_verified"] = True
        report["zip"] = str(archive_path)
    save_reviews(source, items, images, output_path / "_qa" if mode == "render" else output_path, report)
    print(json.dumps({"output": str(output_path), "count": len(items), "scale": scale,
                      "verified": report["files_verified"], "zip": report.get("zip")}, ensure_ascii=False))
    return report


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preview", "render"))
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--edsr-model", type=Path, help="Optional existing EDSR_x4.pb; never downloaded")
    args = parser.parse_args()
    try:
        run(args.mode, args.input, args.layout, args.output, args.edsr_model)
    except (ValueError, OSError, cv2.error) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
