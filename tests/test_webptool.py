#!/usr/bin/env python3

"""
Test webptool.py
"""

import glob
import logging
import os
import shutil
import sys
import unittest
from PIL import Image, ImageDraw

TEST_PATH = os.path.dirname(sys.argv[0])

sys.path.append(os.path.join(TEST_PATH, os.path.pardir))
import webptool

logger = logging.getLogger(__name__)

# External paths, configurable via environment variables

class TestSimple(unittest.TestCase):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._test_path = os.path.join(TEST_PATH, "test-Simple")
    self._name_format = "image-{:04d}.png"
    self._image_count = 100
    self._image_size = (128, 128)

  def _path(self, name):
    return os.path.join(self._test_path, name)

  def _load_input_images(self):
    return webptool.load_images(glob.glob(self._path("image-*.png")))

  def setUp(self):
    if not os.path.exists(self._test_path):
      os.makedirs(self._test_path)
    for index in range(self._image_count):
      fname = self._name_format.format(index)
      fpath = self._path(fname)
      img = Image.new("RGB", self._image_size, color="black")
      draw = ImageDraw.ImageDraw(img)
      draw.text((0, 0), "image-{}".format(index))
      img.save(fpath)

  def tearDown(self):
    if not os.environ.get("TEST_KEEP_DATA"):
      shutil.rmtree(self._test_path)

  def test_is_format_string(self):
    self.assertFalse(webptool.is_format_string(""))
    self.assertTrue(webptool.is_format_string("{}"))
    self.assertFalse(webptool.is_format_string("{{"))
    self.assertFalse(webptool.is_format_string("}}"))
    self.assertFalse(webptool.is_format_string("{{}}"))
    self.assertFalse(webptool.is_format_string("Test"))
    self.assertTrue(webptool.is_format_string("Test {test}"))
    self.assertFalse(webptool.is_format_string("Test {{test}}"))
    self.assertTrue(webptool.is_format_string("Test {}"))
    self.assertFalse(webptool.is_format_string("Test {{}}"))
    self.assertTrue(webptool.is_format_string("Test {:2d}"))
    self.assertFalse(webptool.is_format_string("Test {{:2d}}"))

  def test_deduce_mode(self):
    def test(pin, pout, mode):
      inputs = pin
      if isinstance(pin, str):
        inputs = [pin]
      mode_get = webptool.deduce_mode(inputs, pout)
      self.assertEqual(mode_get, mode)
    MODE_C = webptool.MODE_CREATE
    MODE_E = webptool.MODE_EXTRACT
    test("t.webp", "", MODE_E)
    test("t.webp", "o.webp", MODE_C)
    test("t/t.webp", "", MODE_E)
    test(["t.webp", "v.webp"], "", MODE_E)
    test(["t1.png", "t2.png"], "o.webp", MODE_C)
    test(["t1.webp", "t2.png"], "o.webp", MODE_C)

  def test_is_ready(self):
    self.assertTrue(os.path.isdir(self._test_path))
    files = glob.glob(self._path("*.png"))
    self.assertEqual(len(files), self._image_count)

  def test_create_simple(self):
    images = self._load_input_images()
    opath = webptool.deduce_create_output(self._path("1.webp"))
    if os.path.exists(opath):
      os.unlink(opath)
    self.assertFalse(os.path.exists(opath))
    webptool.create_webp_file(images, opath)
    self.assertTrue(os.path.exists(opath))

  def test_extract_simple(self):
    in_path = self._path("1.webp")
    self.test_create_simple()
    self.assertTrue(os.path.exists(in_path))
    images = webptool.load_images([in_path])

    def test_with_format(out_dirname, out_format):
      out_path = self._path(out_dirname)
      if not os.path.exists(out_path):
        os.makedirs(out_path)
      format_path = os.path.join(out_path, out_format)
      opath = webptool.deduce_extract_output(format_path)
      webptool.extract_webp_file(images, opath)
      gen_files = glob.glob(os.path.join(out_path, "*.png"))
      self.assertEqual(len(gen_files), self._image_count)

    test_with_format("extract", "t-{}.png")
    test_with_format("extract-1", "t-{:04d}.png")
    test_with_format("extract-2", "t-{n:04d}.png")
    test_with_format("extract-3", "t-{n:04d}-{w}x{h}.png")

if __name__ == "__main__":
  if os.environ.get("DEBUG"):
    logger.setLevel(logging.DEBUG)
    webptool.logger.setLevel(logging.DEBUG)
  unittest.main()

# vim: set ts=2 sts=2 sw=2:
