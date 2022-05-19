#!/usr/bin/env python3

"""
Encode a sequence of images to a video file.
"""

import argparse
import logging
import os
import sys

import cv2

logging.basicConfig(format="%(module)s:%(lineno)s: %(levelname)s: %(message)s",
                    level=logging.INFO)
logger = logging.getLogger(__name__)

def deduce_frame_size(inputs, size):
  "Return a pair of (image_width, image_height) in pixels"
  if size and "," in size:
    wstr, hstr = size.split(",", 1)
    return int(wstr), int(hstr)
  logger.debug("Deducing size from %s", inputs[0])
  img = cv2.imread(inputs[0])
  return img.shape[0], img.shape[1]

def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("path", nargs="*", help="frames to encode")
  ap.add_argument("-i", "--input", metavar="PATH",
      help="file with frames to encode, one path per line")
  ap.add_argument("-o", "--output", metavar="PATH",
      help="destination path")
  ap.add_argument("-f", "--format", default="MP4V",
      help="video format (default: %(default)s)")
  ap.add_argument("-n", "--fps", type=int, default=24,
      help="frames per second (default: %(default)s)")
  ap.add_argument("-s", "--size", metavar="W,H",
      help="image size in pixels; deduced if omitted")
  ap.add_argument("-v", "--verbose", action="store_true",
      help="output diagnostic information")
  args = ap.parse_args()
  if args.verbose:
    logger.setLevel(logging.DEBUG)

  paths = args.path
  if args.input is not None:
    with open(args.input, "rt") as fobj:
      paths.extend(fobj.splitlines())

  if not paths:
    ap.error("No images given; nothing to do")

  frame_size = deduce_frame_size(paths, args.size)
  if not args.size:
    logger.debug("Deduced image size: %d by %d pixels", *frame_size)

  logger.info("Writing %d frames to %s at %d fps", len(paths), args.output, args.fps)
  fourcc = cv2.VideoWriter_fourcc(*args.format)
  out = cv2.VideoWriter(args.output, fourcc, args.fps, frame_size)

  for path in paths:
    img = cv2.imread(path)
    logger.debug("Read %s: shape=%s", path, img.shape)
    out.write(img)

  out.release()

if __name__ == "__main__":
  main()

# vim: set ts=2 sts=2 sw=2:
