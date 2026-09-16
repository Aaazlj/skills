"""Behavioral checks for the detail-page circular grid helper using generated fixtures."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from crop_detail_grid import crop_detail_grid, find_empty_circles, prune_overlapping_rows

NAMES = ["白色", "米白色", "浅米色", "浅杏色", "浅卡其色", "姜黄色", "藕粉色", "豆沙粉"]


def textured_circle(radius: int, base, rng) -> tuple[Image.Image, Image.Image]:
    size = radius * 2
    noise = rng.normal(0, 16, size=(size, size, 3))
    patch = np.clip(np.asarray(base, dtype=np.float32) + noise, 0, 255).astype(np.uint8)
    image = Image.fromarray(patch, "RGB")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    return image, mask


class DetailGridTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="detail-grid-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.detail_dir = self.base / "商品" / "详情图"
        self.detail_dir.mkdir(parents=True)
        self.source = self.detail_dir / "详情图01.jpg"
        self.radius = 58
        self.columns = [100, 220, 340, 460]
        self.rows = [220, 420, 620]
        self._build_fixture()

    def _build_fixture(self):
        canvas = Image.new("RGB", (600, 780), (238, 238, 234))
        draw = ImageDraw.Draw(canvas)
        rng = np.random.default_rng(7)
        for row, y in enumerate(self.rows):
            for x in self.columns:
                if row < 2:
                    base = rng.integers(60, 220, size=3)
                    patch, mask = textured_circle(self.radius, base, rng)
                    canvas.paste(patch, (x - self.radius, y - self.radius), mask)
                else:
                    draw.ellipse((x - self.radius, y - self.radius, x + self.radius, y + self.radius),
                                 fill=(247, 247, 244), outline=(150, 150, 148), width=3)
        canvas.save(self.source, quality=95)

    def crop(self, output: Path | None = None, **overrides):
        arguments = {"rows": None, "cols": 4, "min_y_ratio": 0.25}
        arguments.update(overrides)
        return crop_detail_grid(self.source, output, **arguments)

    def test_blank_circles_filtered_and_color_names_applied(self):
        result = self.crop(self.detail_dir.parent / "规格图", names=list(NAMES))
        output = Path(result["output"])
        self.assertEqual(result["count"], 8)
        self.assertEqual(result["skipped"], [9, 10, 11, 12])
        paths = sorted(output.glob("*.png"))
        self.assertEqual([p.name for p in paths], [f"{i:02d}_{name}.png" for i, name in enumerate(NAMES, 1)])
        for path in paths:
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            with Image.open(path) as image:
                self.assertEqual((image.size, image.mode, image.format), ((800, 800), "RGB", "PNG"))
        self.assertFalse(output.with_name(output.name + ".zip").exists())
        self.assertFalse((output / "_qa").exists())

    def test_keep_empty_keeps_all_cells_with_color_names(self):
        twelve = [f"颜色{i:02d}" for i in range(1, 13)]
        result = self.crop(self.detail_dir.parent / "全部", names=twelve, skip_empty=False)
        output = Path(result["output"])
        self.assertEqual(result["count"], 12)
        self.assertEqual(result["skipped"], [])
        self.assertTrue((output / "12_颜色12.png").is_file())
        self.assertTrue((output / "09_颜色09.png").is_file())

    def test_names_are_required(self):
        with self.assertRaisesRegex(ValueError, "必须提供 8 个颜色名"):
            self.crop(self.detail_dir.parent / "无名")

    def test_name_count_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "8 个颜色名"):
            self.crop(self.detail_dir.parent / "错名", names=["白色"])

    def test_find_empty_circles_flags_flat_placeholder(self):
        canvas = Image.new("RGB", (600, 240), (240, 240, 236))
        patch, mask = textured_circle(80, np.array([180, 150, 150]), np.random.default_rng(3))
        canvas.paste(patch, (40, 40), mask)
        ImageDraw.Draw(canvas).ellipse((360, 40, 520, 200), fill=(246, 246, 243), outline=(150, 150, 148), width=3)
        centers = [(120, 120, 80), (440, 120, 80)]
        self.assertEqual(find_empty_circles(canvas, centers), [1])

    def test_phantom_rows_overlapping_kept_rows_are_pruned(self):
        rows = [np.array([(100, 100, 60), (220, 100, 60)]),
                np.array([(100, 220, 60), (220, 220, 60)]),
                np.array([(62, 160, 120), (183, 160, 120)]),
                np.array([(100, 340, 60), (220, 340, 60)])]
        kept = prune_overlapping_rows(rows)
        self.assertEqual([len(row) for row in kept], [2, 2, 2])
        self.assertEqual([float(row[0][1]) for row in kept], [100.0, 220.0, 340.0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
