#!/usr/bin/env python3

"""
Test imagemanage.py
"""

import os
import shutil
import sys
import unittest

TEST_PATH = os.path.dirname(sys.argv[0])

sys.path.append(os.path.join(TEST_PATH, os.path.pardir))
import imagemanage

# External paths, configurable via environment variables
PATH_ICONS = os.environ.get("ICONS_PATH", "/usr/share/icons")
ICON_THEME = os.environ.get("ICONS_THEME", "Yaru")
ICON_SIZE = os.environ.get("ICONS_SIZE", "256x256")

def debug(msg):
  if os.environ.get("DEBUG"):
    sys.stderr.write("DEBUG: " + msg + "\n")

class TestYaru(unittest.TestCase):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._yaru_path = os.path.join(PATH_ICONS, ICON_THEME, ICON_SIZE)
    self._path = os.path.join(TEST_PATH, "test-Yaru")
    print(f"Source: {self._yaru_path}")
    print(f"Dest: {self._path}")
    debug(self.id())
    debug("\n".join(f"{k}={getattr(self, k)!r}" for k in dir(self)))

  def setUp(self):
    if not os.path.exists(self._yaru_path):
      raise unittest.SkipTest(f"{self._yaru_path} does not exist")
    shutil.copytree(self._yaru_path, self._path)
    print(f"Copied {self._yaru_path} to {self._path}")

  def tearDown(self):
    shutil.rmtree(self._path)

  def test_first(self):
    print(self)

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
    self.assertEqual(iterate_from(l, 0), l[1:] + l[:1])
    self.assertEqual(iterate_from(l, 1), l[2:] + l[:2])
    self.assertEqual(iterate_from(l, len(l)-1), l)

  def test_find_images(self):
    # TODO
    pass

  def test_mark1_support(self):
    # TODO
    pass

if __name__ == "__main__":
  unittest.main()

# vim: set ts=2 sts=2 sw=2:
