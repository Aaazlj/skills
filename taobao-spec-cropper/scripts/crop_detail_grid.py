"""Crop circular specification grids embedded in Taobao detail images.

This helper is for long detail images where the SKU choices are shown as a
regular grid of circular swatches with labels such as 'No.01' below them.
It writes only delivery PNG files by default, with no ZIP and no '_qa' folder.
Placeholder circles with no fabric inside (blank last-row cells) are skipped
automatically; pass --keep-empty to keep them. Color names are REQUIRED:
pass --names '白色,米白色,...' so outputs are named 01_白色.png; naming files
after the printed No. labels is not allowed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

from crop_specs import load_image, run as run_crop


def _safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return cleaned or "待确认"


def _cluster_rows(circles: np.ndarray, tolerance: float) -> list[np.ndarray]:
    rows: list[list[np.ndarray]] = []
    for circle in sorted(circles, key=lambda c: (float(c[1]), float(c[0]))):
        if not rows:
            rows.append([circle])
            continue
        center_y = float(np.mean([c[1] for c in rows[-1]]))
        if abs(float(circle[1]) - center_y) <= tolerance:
            rows[-1].append(circle)
        else:
            rows.append([circle])
    return [np.array(sorted(row, key=lambda c: float(c[0]))) for row in rows]


def prune_overlapping_rows(rows: list[np.ndarray], *, max_overlap: float = 0.85) -> list[np.ndarray]:
    """Drop rows whose circles overlap the previous kept row; Hough sees phantom rows this way."""
    kept: list[np.ndarray] = []
    for row in rows:
        if kept and _rows_overlap(kept[-1], row, max_overlap):
            continue
        kept.append(row)
    return kept


def _rows_overlap(row_a: np.ndarray, row_b: np.ndarray, max_overlap: float) -> bool:
    for _, y_a, r_a in row_a:
        for _, y_b, r_b in row_b:
            if abs(float(y_a) - float(y_b)) < max_overlap * (float(r_a) + float(r_b)):
                return True
    return False


def detect_circular_grid(source, *, rows: int | None, cols: int, min_y_ratio: float) -> list[tuple[int, int, int]]:
    """Return circle centers as (x, y, r), row-major."""
    image = np.asarray(source)
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    blur = cv2.medianBlur(gray, 5)
    min_radius = max(24, int(source.width * 0.045))
    max_radius = max(min_radius + 8, int(source.width * 0.12))
    min_dist = max(40, int(source.width / (cols + 3)))
    best: list[np.ndarray] = []
    best_score: tuple[int, int, float] | None = None
    for param2 in (46, 42, 50, 38, 34, 30, 26):
        found = cv2.HoughCircles(
            blur,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=min_dist,
            param1=90,
            param2=param2,
            minRadius=min_radius,
            maxRadius=max_radius,
        )
        if found is None:
            continue
        circles = np.round(found[0]).astype(int)
        circles = circles[
            (circles[:, 1] >= int(source.height * min_y_ratio))
            & (circles[:, 0] >= int(source.width * 0.04))
            & (circles[:, 0] <= int(source.width * 0.96))
        ]
        if not len(circles):
            continue
        tolerance = max(22, int(np.median(circles[:, 2]) * 0.75))
        grouped = [row for row in _cluster_rows(circles, tolerance) if len(row) >= cols]
        complete = prune_overlapping_rows([row[:cols] for row in grouped if len(row) == cols])
        if rows is not None and len(complete) >= rows:
            candidate = complete[:rows]
        else:
            candidate = complete
        if not candidate:
            continue
        y_values = [float(np.mean(row[:, 1])) for row in candidate]
        spacing_noise = 0.0 if len(y_values) < 3 else float(np.std(np.diff(y_values)))
        score = (len(candidate), sum(len(row) for row in candidate), -spacing_noise)
        if best_score is None or score > best_score:
            best_score = score
            best = candidate
    if rows is not None and len(best) < rows:
        raise ValueError(f"只检测到 {len(best)} 行圆形规格，少于要求的 {rows} 行")
    if rows is None:
        rows = len(best)
    selected = best[:rows]
    if len(selected) != rows or any(len(row) != cols for row in selected):
        raise ValueError("无法稳定识别圆形规格网格；请改用 layout JSON 手动指定 box")
    centers: list[tuple[int, int, int]] = []
    for row in selected:
        for x, y, radius in row[:cols]:
            centers.append((int(x), int(y), int(radius)))
    return centers


EMPTY_STD_MAX = 6.0
EMPTY_SPREAD_MAX = 15.0


def find_empty_circles(source, centers: list[tuple[int, int, int]], *, radius_ratio: float = 0.72,
                       max_std: float = EMPTY_STD_MAX, max_spread: float = EMPTY_SPREAD_MAX) -> list[int]:
    """Return 0-based indices of blank placeholder circles (no fabric texture inside)."""
    gray = np.asarray(source.convert("L")).astype(np.float32)
    height, width = gray.shape
    empty: list[int] = []
    for index, (x, y, radius) in enumerate(centers):
        reach = radius * radius_ratio
        y0, y1 = max(0, int(y - reach)), min(height, int(y + reach) + 1)
        x0, x1 = max(0, int(x - reach)), min(width, int(x + reach) + 1)
        patch = gray[y0:y1, x0:x1]
        local_y, local_x = np.mgrid[y0:y1, x0:x1]
        mask = (local_x - x) ** 2 + (local_y - y) ** 2 <= reach * reach
        values = patch[mask]
        spread = float(np.percentile(values, 95) - np.percentile(values, 5))
        if float(values.std()) < max_std and spread < max_spread:
            empty.append(index)
    return empty


def build_layout(source, centers: list[tuple[int, int, int]], *, cols: int,
                 names: list[str]) -> dict:
    row_chunks = [centers[index:index + cols] for index in range(0, len(centers), cols)]
    row_values = [int(round(float(np.mean([y for _, y, _ in row])))) for row in row_chunks]
    radii = [r for _, _, r in centers]
    radius = int(np.median(radii))
    x_pitch = int(np.median(np.diff(sorted([x for x, _, _ in centers[:cols]])))) if cols > 1 else radius * 3
    y_pitch = int(np.median(np.diff(row_values))) if len(row_values) > 1 else radius * 3
    x_half = max(radius + 18, int(x_pitch * 0.44))
    y_top_default = max(radius + 18, int(y_pitch * 0.44))
    # Leave enough room for the No. label, but never let a cell box cross the
    # midpoint to the next detected row. Crossing that midpoint is what causes
    # the next swatch to appear as a thin strip at the bottom of every output.
    y_bottom_default = max(radius + 38, int(y_pitch * 0.42))
    items = []
    for index, (x, y, _) in enumerate(centers, 1):
        row_index = (index - 1) // cols
        row_y = row_values[row_index]
        row_top = 0 if row_index == 0 else int(round((row_values[row_index - 1] + row_y) / 2))
        row_bottom = source.height if row_index == len(row_values) - 1 else int(round((row_y + row_values[row_index + 1]) / 2))
        left = max(0, x - x_half)
        top = max(row_top, y - y_top_default)
        right = min(source.width, x + x_half)
        bottom = min(row_bottom, y + y_bottom_default)
        items.append({
            "color": _safe_name(names[index - 1]),
            "box": [int(left), int(top), int(right), int(bottom)],
            "alignment": "content",
            "trim": False,
        })
    return {
        "source_size": [source.width, source.height],
        "options": {"alignment": "content", "content_width": 660, "margin": 32},
        "items": items,
    }


def default_output_for(input_path: Path) -> Path:
    if input_path.parent.name == "详情图":
        return input_path.parent.parent / "规格图"
    return input_path.parent / "规格图"


def crop_detail_grid(input_path: Path, output_path: Path | None, *, rows: int | None, cols: int,
                     min_y_ratio: float, names: list[str] | None = None,
                     skip_empty: bool = True) -> dict:
    input_path = input_path.resolve()
    output_path = (output_path or default_output_for(input_path)).resolve()
    source = load_image(input_path)
    centers = detect_circular_grid(source, rows=rows, cols=cols, min_y_ratio=min_y_ratio)
    skipped = find_empty_circles(source, centers) if skip_empty else []
    skipped_set = set(skipped)
    kept = [center for index, center in enumerate(centers) if index not in skipped_set]
    if names is None:
        raise ValueError(f"必须提供 {len(kept)} 个颜色名（--names '白色,米白色,…'），文件名不允许使用 No. 编号")
    if len(names) != len(kept):
        raise ValueError(f"--names 需要 {len(kept)} 个颜色名（已跳过 {len(skipped)} 个空白占位圆，实际传入 {len(names)} 个）")
    layout = build_layout(source, kept, cols=cols, names=names)
    with tempfile.TemporaryDirectory(prefix="taobao-detail-grid-") as tmp:
        layout_path = Path(tmp) / "layout.json"
        layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
        report = run_crop("render", input_path, layout_path, output_path, make_zip=False, make_qa=False)
    return {"output": str(output_path), "count": len(kept), "centers": kept,
            "skipped": [index + 1 for index in skipped], "crop_report": report}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="默认输出到详情图上一级的 规格图 目录")
    parser.add_argument("--rows", type=int, help="规格行数；不传则使用检测到的完整行")
    parser.add_argument("--cols", type=int, default=4, help="规格列数，默认 4")
    parser.add_argument("--min-y-ratio", type=float, default=0.25, help="忽略图片顶部比例，默认 0.25")
    parser.add_argument("--names", required=True,
                        help="逗号分隔的中文颜色名，按顺序命名 01_颜色.png；必填，数量必须与有效色卡一致，不允许用 No. 编号做文件名")
    parser.add_argument("--keep-empty", action="store_true", help="保留没有布片的空白占位圆（默认自动跳过）")
    args = parser.parse_args()
    if args.cols <= 0:
        parser.error("--cols 必须为正整数")
    if args.rows is not None and args.rows <= 0:
        parser.error("--rows 必须为正整数")
    names = [part.strip() for part in re.split(r"[,，]", args.names) if part.strip()]
    if not names:
        parser.error("--names 不能为空")
    try:
        result = crop_detail_grid(args.input, args.output, rows=args.rows, cols=args.cols,
                                  min_y_ratio=args.min_y_ratio,
                                  names=names, skip_empty=not args.keep_empty)
    except (ValueError, OSError, cv2.error) as exc:
        parser.exit(2, f"错误：{exc}\n")
    print(json.dumps({"output": result["output"], "count": result["count"],
                      "skipped": result["skipped"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
