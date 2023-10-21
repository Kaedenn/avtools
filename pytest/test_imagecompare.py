#!/usr/bin/env python3

"""
Test suite for imagecompare.py
"""

import pytest
import glob
import os
import shutil
import sys

import imagecompare
from imagecompare import PixelMethod
from helpers.debugging import *

def test_pixel_alg():
  assert PixelMethod.Red(255, 0, 0) == 1
  assert PixelMethod.Hue(255, 0, 0) == 0
  assert PixelMethod.Hue(0, 0, 0) == 0
  assert PixelMethod.Hue(10, 10, 10) == 0
  assert PixelMethod.Hue(255, 255, 255) == 0
  assert PixelMethod.Hue(0, 255, 0) == 360/3
  assert PixelMethod.Hue(0, 0, 255) == 360*2/3

# vim: set ts=2 sts=2 sw=2:
