#!/usr/bin/env python3

"""
Report if two images are "the same" by comparing pixels
"""

# TODO: implement true "color difference" (see tfc)
# TODO: improve operation speed by using numpy

import argparse
import enum
import logging
import math
import os
import sys

from PIL import Image

logging.basicConfig(format="%(module)s:%(lineno)s: %(levelname)s: %(message)s",
                    level=logging.INFO)
logger = logging.getLogger(__name__)

THRESH_DEFAULT = 0.9    # 90%, differ by less than 10%

def _rescale_pixel(r, g, b, a=None):
  "Rescale the pixel values from 0-255 to 0-1"
  alpha = a/255 if a is not None else 0
  return r/255, g/255, b/255, alpha

class PixelMethod:
  "How do we convert a pixel (RGBa) to a single number?"

  def LinearRGB(r, g, b, a=None):
    "(r + g + b)/3; ignores alpha"
    pr, pg, pb, pa = _rescale_pixel(r, g, b, a)
    return (pr + pg + pb) / 3

  def LinearRGBA(r, g, b, a=None):
    "(r + g + b + a)/3"
    pr, pg, pb, pa = _rescale_pixel(r, g, b, a)
    return (pr + pg + pb + pa) / 3

  def QuadraticRGB(r, g, b, a=None):
    "sqrt(r^2 + g^2 + b^2); ignores alpha"
    pr, pg, pb, pa = _rescale_pixel(r, g, b, a)
    return (pr**2 + pg**2 + pb**2) ** 0.5

  def QuadraticRGBA(r, g, b, a=None):
    "sqrt(r^2 + g^2 + b^2 + a^2)"
    pr, pg, pb, pa = _rescale_pixel(r, g, b, a)
    return (pr**2 + pg**2 + pb**2 + pa**2) ** 0.5

  def Red(r, g, b, a=None):
    "Value of the red channel"
    return r/255

  def Green(r, g, b, a=None):
    "Value of the green channel"
    return g/255

  def Blue(r, g, b, a=None):
    "Value of the blue channel"
    return b/255

  def Alpha(r, g, b, a=None):
    "Value of the alpha channel, or 0 if there is no alpha channel"
    return a if a is not None else 0

  def Hue(r, g, b, a=None):
    "Pixel's hue, from 0 to 360"
    rgb = (r, g, b)
    maxval = max(rgb)
    minval = min(rgb)
    delta = maxval - minval
    if delta == 0:
      return 0
    rval, gval, bval = r/255, g/255, b/255
    dval = max((rval, gval, bval)) - min((rval, gval, bval))
    sector = 0
    if maxval == r:
      sector = ((gval - bval) / dval)
    if maxval == g:
      sector = ((bval - rval) / dval) + 2
    if maxval == b:
      sector = ((rval - gval) / dval) + 4
    return int(sector * 60) % 360

  values = (
    ("LinearRGB", LinearRGB),
    ("LinearRGBA", LinearRGBA),
    ("QuadraticRGB", QuadraticRGB),
    ("QuadraticRGBA", QuadraticRGBA),
    ("Red", Red),
    ("Green", Green),
    ("Blue", Blue),
    ("Alpha", Alpha),
    ("Hue", Hue)
  )

class ValueMethod:
  """How do we determine how 'far apart' two numbers are? Results are between
  0 and 1, where the smaller the value, the closer the two numbers are."""
  def Difference(v1, v2):
    "Linear difference between v1 and v2, rescaled to the interval [0, 1]"
    return abs(v1, v2) / max(v1, v2)

  def Quotient(v1, v2):
    "Simple quotient v1 / v2, adjusted to the interval [0, 1]"
    return 1 - min(v1, v2) / max(v1, v2)

  def Trigonometric(v1, v2):
    "Arc-tangent of v1 and v2, adjusted to the interval [0, 1]"
    return 1 - 4 / math.pi * math.atan2(min(v1, v2), max(v1, v2))

  values = (
    ("Difference", Difference),
    ("Quotient", Quotient),
    ("Trigonometric", Trigonometric)
  )

def compare_image_sizes(image1, image2):
  "True if the images are the same size (or same aspect ratio)"
  if image1.width == image2.width and image1.height == image2.height:
    return True

  aspect1 = image1.width / image1.height
  aspect2 = image2.width / image2.height
  if round(aspect1 * 100) == round(aspect2 * 100):
    return True

  logger.debug("images %r and %r differ by size: %dx%d r=%f, %dx%d r=%f",
      image1.filename, image2.filename,
      image1.width, image1.height, aspect1,
      image2.width, image2.height, aspect2)
  return False

def maybe_rescale(image1, image2):
  "If necessary, rescale the larger of the two images so that sizes match"
  if image1.width < image2.width:
    target_w, target_h = image1.width, image1.height
    logger.debug("recaling image %r from %dx%d to %dx%d",
        image2.filename, image2.width, image2.height, target_w, target_h)
    image2 = image2.resize((target_w, target_h))
  elif image1.width > image2.width:
    target_w, target_h = image2.width, image2.height
    logger.debug("recaling image %r from %dx%d to %dx%d",
        image1.filename, image1.width, image1.height, target_w, target_h)
    image1 = image1.resize((target_w, target_h))

  return image1, image2

def compare_images(image1, image2,
    pixel_method=PixelMethod.QuadraticRGB,
    value_method=ValueMethod.Trigonometric,
    threshold=THRESH_DEFAULT,
    ignore_size=False,
    skip_rescale=False,
    progress=False):
  """
  Compare the two images, returning a confidence value between 0 and 1

  pixel_method  function that converts a pixel (rgb[a]) to a number
  value_method  function that compares two numbers for approximate equality
  threshold     pixels are equal if their values are within this percent
                using 0.9 means the values differ by less than 10%
  ignore_size   if True, don't worry if the images differ in size
  skip_rescale  if True, don't resize the images to match

  The result is the percentage of the image's pixels that satisfy the given
  threshold.
  """
  if isinstance(pixel_method, PixelMethod):
    pixel_method = pixel_method.value
  if isinstance(value_method, ValueMethod):
    value_method = value_method.value
  cutoff = 1 - threshold

  logger.debug("Comparing %r with %r", image1.filename, image2.filename)
  if not ignore_size:
    if not compare_image_sizes(image1, image2):
      logger.info("Images %r and %r differ by size: %dx%d != %dx%d",
          image1.filename, image2.filename,
          image1.width, image1.height, image2.width, image2.height)
      return 0

  if not skip_rescale:
    image1, image2 = maybe_rescale(image1, image2)

  match_pixels = 0
  width_max = min(image1.width, image2.width)
  height_max = min(image1.height, image2.height)
  total_pixels = width_max * height_max
  for rpixel in range(width_max):
    if progress is not False:
      sys.stderr.write("{}/{} {:.02f}%\r".format(
        rpixel, width_max, rpixel * 100 / width_max))
    for cpixel in range(height_max):
      pixel1 = image1.getpixel((rpixel, cpixel))
      pixel2 = image2.getpixel((rpixel, cpixel))
      value1 = pixel_method(*pixel1)
      value2 = pixel_method(*pixel2)
      difference = value_method(value1, value2)
      if difference <= cutoff:
        match_pixels += 1

  logger.debug("%d pixels match of a total of %d pixels (%.02f%%) (%dx%d)",
      match_pixels, total_pixels,
      match_pixels * 100 / total_pixels,
      image1.width, image1.height)
  return match_pixels / total_pixels

def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("images", nargs="+", help="path to images")
  ap.add_argument("-P", "--pixel-method",
      choices=[method[0] for method in PixelMethod.values], default="QuadraticRGB",
      help="pixel-to-number calculation method (default: %(default)s)")
  ap.add_argument("-V", "--value-method",
      choices=[method[0] for method in ValueMethod.values], default="Trigonometric",
      help="value comparison method (default: %(default)s)")
  ap.add_argument("-t", "--threshold", metavar="NUM", type=float,
      default=THRESH_DEFAULT,
      help="pixels are equal if they differ by less than (1-%(metavar)s)*100 "
           "percent (default: %(default)s)")
  ap.add_argument("-S", "--ignore-size", action="store_true",
      help="continue even if the images differ by size and aspect ratio")
  ap.add_argument("--skip-rescale", action="store_true",
      help="do not rescale the images to have the same size")
  ap.add_argument("-p", "--progress", action="store_true", help="display progress")
  ap.add_argument("-v", "--verbose", action="store_true", help="verbose output")
  args = ap.parse_args()
  if args.verbose:
    logger.setLevel(logging.DEBUG)

  image_list = args.images
  if args.images == ["-"]:
    image_list = sys.stdin.read().splitlines()
  if len(image_list) < 2:
    ap.error("Too few images")

  compare_sets = []
  images = {image: Image.open(image) for image in image_list}
  for index, path1 in enumerate(image_list):
    for path2 in image_list[index+1:]:
      compare_sets.append((path1, path2))
  nsets = len(compare_sets)

  for index, image_pair in enumerate(compare_sets):
    image1, image2 = image_pair
    logger.info("%d/%d: Comparing %s and %s", index+1, nsets, image1, image2)

    confidence = compare_images(images[image1], images[image2],
        pixel_method=dict(PixelMethod.values)[args.pixel_method],
        value_method=dict(ValueMethod.values)[args.value_method],
        threshold=args.threshold,
        ignore_size=args.ignore_size,
        skip_rescale=args.skip_rescale,
        progress=args.progress)
    print(confidence, image1, image2)

if __name__ == "__main__":
  main()

# vim: set ts=2 sts=2 sw=2:
