#!/usr/bin/env python3

"""
Test imagemanage.py
"""

import os
import shutil
import sys
import unittest
from PIL import Image, ImageDraw

TEST_PATH = os.path.dirname(sys.argv[0])

sys.path.append(os.path.join(TEST_PATH, os.path.pardir))
import imagemanage

def _build_dataset(test_path, n=8, size=(32, 32)):
  "Create images for testing"
  for nr in range(n):
    name = "image-{}x{}-{:02d}.png".format(size[0], size[1], nr)
    image = Image.new("RGB", size, color="black")
    draw = ImageDraw.ImageDraw(image)
    draw.text((0, 0), name)
    image.save(os.path.join(test_path, name))

class TestImages(unittest.TestCase):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._path = os.path.join(TEST_PATH, f"test-images")
    self._icount = int(os.environ.get("IMAGE_COUNT", "8"))
    self._isize = (32, 32) # TODO: configurable

  def setUp(self):
    path = os.path.join(self._path, "{}x{}".format(*self._isize))
    if not os.path.exists(path):
      os.makedirs(path)
    _build_dataset(path, self._icount, self._isize)

  def tearDown(self):
    if not os.environ.get("TEST_KEEP"):
      shutil.rmtree(self._path)

  def test_get_images(self):
    images_none = imagemanage.get_images(self._path)
    self.assertFalse(images_none)
    images_all = imagemanage.get_images(self._path, recursive=True)
    self.assertTrue(images_all)

  # TODO: test the actual class

class TestUtilityFunctions(unittest.TestCase):
  def test_format_size(self):
    self.assertEqual(imagemanage.format_size(1), "1 B")
    self.assertEqual(imagemanage.format_size(1023), "1023 B")
    self.assertEqual(imagemanage.format_size(1024, places=0), "1 KB")
    self.assertEqual(imagemanage.format_size(1024, places=1), "1.0 KB")
    self.assertEqual(imagemanage.format_size(1025, places=0), "1 KB")
    self.assertEqual(imagemanage.format_size(1025, places=1), f"{1025/1024:.01f} KB")
    self.assertEqual(imagemanage.format_size(1024**2), "1.0 MB")
    self.assertEqual(imagemanage.format_size(1024**2, places=0), "1 MB")
    self.assertEqual(imagemanage.format_size(1024**3), "1.0 GB")
    self.assertEqual(imagemanage.format_size(1024**3, places=0), "1 GB")
    self.assertEqual(imagemanage.format_size(1024**4), "1.0 TB")
    self.assertEqual(imagemanage.format_size(1024**4, places=0), "1 TB")
    self.assertEqual(imagemanage.format_size(1024**5), "1.0 PB")
    self.assertEqual(imagemanage.format_size(1024**5, places=0), "1 PB")
    self.assertEqual(imagemanage.format_size(1024**6), "1024.0 PB")
    self.assertEqual(imagemanage.format_size(1024**6, places=0), "1024 PB")

  def test_iterate_from(self):
    iterate_from = lambda l, i: list(imagemanage.iterate_from(l, i))
    l = list(range(10))
    self.assertEqual(iterate_from(l, 0), l)
    self.assertEqual(iterate_from(l, 1), l[1:] + l[:1])
    self.assertEqual(iterate_from(l, len(l)), l)

  def test_is_image(self):
    self.assertTrue(imagemanage.is_image("foo.png"))
    self.assertTrue(imagemanage.is_image("foo.jpg"))
    self.assertTrue(imagemanage.is_image("foo.jpeg"))
    self.assertTrue(imagemanage.is_image("foo.gif"))
    self.assertFalse(imagemanage.is_image("foo"))
    self.assertFalse(imagemanage.is_image("foo.mpg"))

if __name__ == "__main__":
  unittest.main()

# vim: set ts=2 sts=2 sw=2:
