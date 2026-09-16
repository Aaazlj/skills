"""Behavioral checks using isolated, generated fixtures; no project images are changed."""

import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from crop_specs import (compose, load_image, options_for, prepare_items, run,
                        shared_scale)


class CropSpecsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="spec-crop-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source_path = self.base / "含 空格的原图.png"
        self.plan_path = self.base / "裁切.json"
        self.image = Image.new("RGB", (600, 520), "white")
        draw = ImageDraw.Draw(self.image)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 24)
        except OSError:
            font = ImageFont.truetype("DejaVuSans.ttf", 24)
        self.numbers = []
        for index, (label, color, dx, dy) in enumerate([
            ("1", "#ffe49a", 13, 0), ("10", "#376cad", -11, 3),
            ("101", "#b4d3a5", 5, -2),
        ]):
            x, y = index % 2 * 300, index // 2 * 260
            draw.rectangle((x + 42, y + 30, x + 258, y + 166), fill=color)
            if index == 1:
                # Dark cloth fringes can extend into the initial label search band.
                for start in (105, 122, 139):
                    draw.rectangle((x + start, y + 178, x + start + 9, y + 185), fill="#111111")
            anchor = (x + 150 + dx, y + 200 + dy)
            draw.text(anchor, label, fill="black", font=font, anchor="mt")
            self.numbers.append(draw.textbbox(anchor, label, font=font, anchor="mt"))
            if index == 0:
                draw.text((x + 163, y + 235), "EXTRA", fill="black", anchor="mt")
        self.plan = {
            "source_size": [600, 520],
            "grid": {"x_edges": [0, 300, 600], "y_edges": [0, 260, 520], "row_counts": [2, 1]},
            "items": [{"color": "浅黄色"}, {"color": "蓝色"}, {"color": "浅绿色"}],
        }
        self.image.save(self.source_path)
        self.write_plan()

    def write_plan(self):
        self.plan_path.write_text(json.dumps(self.plan, ensure_ascii=False), encoding="utf-8")

    def render(self, output="result", mode="render"):
        self.write_plan()
        with contextlib.redirect_stdout(io.StringIO()):
            return run(mode, self.source_path, self.plan_path, self.base / output,
                       make_zip=True, make_qa=True)

    def test_grid_number_alignment_png_and_zip(self):
        report = self.render()
        paths = sorted((self.base / "result").glob("*.png"))
        self.assertEqual(len(paths), 3)
        self.assertTrue(report["files_verified"])
        for path in paths:
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            with Image.open(path) as image:
                self.assertEqual((image.size, image.mode, image.format), ((800, 800), "RGB", "PNG"))
                # Independent ink measurement, including 1-, 2-, and 3-digit labels.
                region = np.asarray(image)[510:611, 280:520]
                ys, xs = np.nonzero(np.max(region, axis=2) < 160)
                self.assertLessEqual(abs((xs.min() + xs.max() + 1) / 2 + 280 - 400), 0.5)
                self.assertEqual(int(ys.max()) + 1 + 510, 590)
                self.assertTrue(np.all(np.asarray(image)[0] == 255))
        with zipfile.ZipFile(self.base / "result.zip") as archive:
            self.assertEqual(archive.namelist(), [p.name for p in paths])
            self.assertIsNone(archive.testzip())
        self.assertTrue((self.base / "result" / "_qa" / "contact-sheet.png").is_file())
        self.assertTrue((self.base / "result" / "_qa" / "report.json").is_file())
        # The original color pixels were not altered, and the original file remains untouched.
        self.assertEqual(load_image(self.source_path).getpixel((100, 100)), (255, 228, 154))

    def test_explicit_number_boxes(self):
        for item, box in zip(self.plan["items"], self.numbers):
            item["number_box"] = list(box)
        report = self.render()
        for item in report["items"]:
            self.assertEqual(item["output_number_box"][3], 590)

    def test_number_detection_excludes_cloth_fringe_and_extra_text(self):
        items = prepare_items(self.image, self.plan, options_for(self.plan))
        for item, expected in zip(items, self.numbers):
            actual = item.number_box
            self.assertGreaterEqual(actual[0], expected[0])
            self.assertGreaterEqual(actual[1], expected[1])
            self.assertLessEqual(actual[2], expected[2])
            self.assertLessEqual(actual[3], expected[3])

    def test_preview_does_not_create_delivery_zip(self):
        report = self.render(mode="preview")
        self.assertFalse(report["files_verified"])
        self.assertFalse((self.base / "result.zip").exists())
        self.assertTrue((self.base / "result" / "source-boxes.png").exists())

    def test_render_skips_zip_and_qa_by_default(self):
        self.write_plan()
        with contextlib.redirect_stdout(io.StringIO()):
            report = run("render", self.source_path, self.plan_path, self.base / "plain")
        self.assertTrue(report["files_verified"])
        self.assertFalse((self.base / "plain.zip").exists())
        self.assertFalse((self.base / "plain" / "_qa").exists())
        self.assertEqual(len(list((self.base / "plain").glob("*.png"))), 3)

    def test_existing_directory_and_zip_are_preserved(self):
        self.render()
        previous = (self.base / "result.zip").read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.render()
        self.assertEqual((self.base / "result.zip").read_bytes(), previous)
        (self.base / "another.zip").write_bytes(b"existing archive")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.render("another")
        self.assertFalse((self.base / "another").exists())
        self.assertEqual((self.base / "another.zip").read_bytes(), b"existing archive")

    def test_missing_number_does_not_fake_success(self):
        self.plan["items"][0]["number_box"] = [0, 0, 20, 20]
        with self.assertRaisesRegex(ValueError, "No dark label"):
            self.render()
        self.assertFalse((self.base / "result").exists())

    def test_invalid_layout_is_rejected(self):
        for field, value in (("source_size", [600, 519]), ("items", self.plan["items"][:2])):
            with self.subTest(field=field):
                invalid = {**self.plan, field: value}
                with self.assertRaises(ValueError):
                    prepare_items(self.image, invalid, options_for(invalid))
        self.plan["items"][0]["box"] = [-1, 0, 300, 260]
        with self.assertRaisesRegex(ValueError, "outside"):
            self.render()

    def test_transparent_single_image_centered_without_number(self):
        rgba = Image.new("RGBA", (120, 80), (0, 0, 0, 0))
        ImageDraw.Draw(rgba).rectangle((20, 20, 99, 59), fill=(255, 0, 0, 255))
        rgba.save(self.source_path)
        self.plan = {"source_size": [120, 80], "items": [
            {"color": "红色", "box": [0, 0, 120, 80], "alignment": "content"}
        ]}
        report = self.render()
        self.assertIsNone(report["items"][0]["output_number_box"])
        with Image.open(self.base / "result" / "01_红色.png") as result:
            self.assertEqual(result.getpixel((0, 0)), (255, 255, 255))
            self.assertEqual(result.getpixel((400, 400)), (255, 0, 0))
            arr = np.asarray(result)
            ys, xs = np.nonzero((arr[:, :, 0] > 220) & (arr[:, :, 1] < 30))
            self.assertLessEqual(abs((xs.min() + xs.max() + 1) / 2 - 400), 0.5)
            self.assertLessEqual(abs((ys.min() + ys.max() + 1) / 2 - 400), 0.5)

    def test_tall_content_is_not_clipped(self):
        source = Image.new("RGB", (200, 900), "#ff5555")
        plan = {"source_size": [200, 900], "items": [
            {"color": "红色", "box": [0, 0, 200, 900], "alignment": "content", "trim": False}
        ]}
        options = options_for(plan)
        items = prepare_items(source, plan, options)
        output, record = compose(items[0], shared_scale(items, options), options)
        self.assertGreaterEqual(record["paste_box"][1], 32)
        self.assertLessEqual(record["paste_box"][3], 768)
        self.assertEqual(output.getpixel((400, 400)), (255, 85, 85))

    def test_grayscale_alpha_uses_white_background(self):
        grayscale = Image.new("LA", (80, 60), (0, 0))
        grayscale.putpixel((40, 30), (50, 255))
        grayscale.save(self.source_path)
        loaded = load_image(self.source_path)
        self.assertEqual(loaded.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(loaded.getpixel((40, 30)), (50, 50, 50))

    def test_exif_orientation_is_applied_before_coordinate_check(self):
        image = Image.new("RGB", (120, 80), "white")
        exif = Image.Exif()
        exif[274] = 6
        path = self.base / "rotated.jpg"
        image.save(path, exif=exif)
        self.assertEqual(load_image(path).size, (80, 120))


if __name__ == "__main__":
    unittest.main(verbosity=2)
