#!/usr/bin/env python3

"""
Test suite for imagemanage.py
"""

import pytest
import glob
import os
import shutil
import sys

import imagemanage
from helpers.debugging import *

# Present to isolate failures in creating the local icons folder
def test_yaru_first(local_icons):
  assert os.path.isdir(local_icons)
  assert len(glob.glob(os.path.join(local_icons, "*", "*.png"))) > 0

def test_util_format_size():
  assert imagemanage.format_size(1) == "1 B"
  assert imagemanage.format_size(1023) == "1023 B"
  assert imagemanage.format_size(1024, places=0) == "1 KB"
  assert imagemanage.format_size(1024, places=1) == "1.0 KB"
  assert imagemanage.format_size(1025, places=0) == "1 KB"
  assert imagemanage.format_size(1025, places=1) == f"{1025/1024:.01f} KB"
  assert imagemanage.format_size(1024**2) == "1.0 MB"
  assert imagemanage.format_size(1024**2, places=0) == "1 MB"
  assert imagemanage.format_size(1024**3) == "1.0 GB"
  assert imagemanage.format_size(1024**3, places=0) == "1 GB"
  assert imagemanage.format_size(1024**4) == "1.0 TB"
  assert imagemanage.format_size(1024**4, places=0) == "1 TB"
  assert imagemanage.format_size(1024**5) == "1.0 PB"
  assert imagemanage.format_size(1024**5, places=0) == "1 PB"
  assert imagemanage.format_size(1024**6) == "1024.0 PB"
  assert imagemanage.format_size(1024**6, places=0) == "1024 PB"

def test_util_iterate_from():
  iterate_from = lambda l, i: list(imagemanage.iterate_from(l, i))
  l = list(range(10))
  assert iterate_from(l, 0) == l[:]
  assert iterate_from(l, 1) == l[1:] + l[:1]
  assert iterate_from(l, len(l)) == l

def test_get_images(local_icons):
  images_none = imagemanage.get_images(local_icons)
  assert len(images_none) == 0
  images_all = imagemanage.get_images(local_icons, recursive=True)
  assert len(images_all) > 0

# vim: set ts=2 sts=2 sw=2:
