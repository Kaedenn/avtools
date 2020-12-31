#!/usr/bin/env python3

"""
Test imagemanage.py
"""

import os
import sys
import unittest

sys.path.append(os.path.join(os.path.dirname(sys.argv[0]), os.path.pardir))
import imagemanage

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
