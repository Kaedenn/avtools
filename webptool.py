#!/usr/bin/env python3

"""
Create or split WebP images
"""

import argparse
import logging
import os
import string
import sys

import webp
from PIL import Image
import cv2

logging.basicConfig(level=logging.INFO,
    format="%(module)s:%(lineno)s: %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MODE_CREATE = "create-webp"
MODE_EXTRACT = "extract-webp"
MODE_ENCODE = "encode-video"
DEFAULT_WEBP_NAME = "image.webp"
DEFAULT_NAME_FORMAT = "image-{:04d}.png"

def is_format_string(value):
  "Return True if the string contains str.format() sequences"
  fields = list(string.Formatter().parse(value))
  for (literal, name, spec, conv) in string.Formatter().parse(value):
    if not (name is None and spec is None and conv is None):
      return True
  return False

def gather_inputs(path_arg, input_arg):
  "Interpret the two arguments into a list of paths"
  def iter_inputs():
    # pylint: disable=missing-function-docstring
    for path in path_arg:
      yield path
    if input_arg is not None:
      with open(input_arg, "rt") as fobj:
        for line in fobj:
          yield line.rstrip()

  results = []
  for path in iter_inputs():
    if os.path.exists(path):
      results.append(path)
    else:
      logger.warning("Ignoring %r: path doesn't exist", path)
  return results

def load_images(paths):
  "Create a list of PIL images, handling WebP files as multiple images"
  results = []
  for path in paths:
    if path.endswith(".webp"):
      results.extend(webp.load_images(path))
    else:
      results.append(Image.open(path))
  return results

def deduce_mode(paths_in, path_out):
  "Determine what we're doing: creating or extracting WebP image(s)"
  if path_out.endswith(".webp"):
    return MODE_CREATE
  if any(path.endswith(".webp") for path in paths_in):
    return MODE_EXTRACT
  if is_format_string(path_out):
    return MODE_EXTRACT
  # Failed to deduce mode
  return None

def deduce_create_output(path_out):
  "Determine final output path for the create mode"
  if path_out is None:
    logger.warning("Unknown output path; using {}".format(DEFAULT_WEBP_NAME))
    return DEFAULT_WEBP_NAME
  if os.path.isdir(path_out):
    outpath = os.path.join(path_out, DEFAULT_WEBP_NAME)
    logger.warning("Output path is a directory; using {}".format(outpath))
    return outpath
  if not path_out.endswith(".webp"):
    logger.warning("Output path does not end in .webp; continuing anyway")
  return path_out

def deduce_extract_output(path_out):
  "Determine final output format for the extract mode"
  outpath = path_out
  if path_out is None:
    outpath = os.path.join(os.curdir, DEFAULT_NAME_FORMAT)
    logger.warning("Unknown output path; using {}".format(outpath))
  elif os.path.isdir(path_out):
    outpath = os.path.join(path_out, DEFAULT_NAME_FORMAT)
    logger.warning("Output path is a directory; using {}".format(outpath))
  elif not is_format_string(path_out):
    logger.warning("Output path is not a format string; expect errors")
  return outpath

def format_extract_filename(format_out, frame_number, **kwds):
  "Format a final output file path using the given the format arguments"
  class FormatAllowMissing(string.Formatter):
    def get_value(self ,key, args, kwargs):
      if isinstance(key, int):
        if key < len(args):
          return args[key]
      elif key in kwargs:
        return kwargs[key]
      return key
  return FormatAllowMissing().format(format_out, frame_number, **kwds)

def write_video(images, output_path, size_wxh=None, fps=24, encoder='MP4V'):
  "Create a video file (default MP4 video) from the given image paths"
  fourcc = cv2.VideoWriter_fourcc(*encoder)
  logger.debug("Saving %d images to %s...", len(images), output_path)
  if size_wxh is None:
    logger.debug("Size not given; deducing from %s", images[0])
    bounds = Image.open(images[0]).getbbox()
    size_wxh = bounds[2], bounds[3]
  out = cv2.VideoWriter(output_path, fourcc, fps, size_wxh)
  for image in images:
    img = cv2.imread(image)
    out.write(img)
  out.release()

def create_webp_file(images, output_path, fps=None):
  "Create a WebP file from the given images"
  kwargs = {}
  if fps is not None:
    kwargs["fps"] = fps
  logger.debug("Saving images to %s...", output_path)
  webp.save_images(images, output_path, **kwargs)

def extract_webp_file(images, oformat):
  "Extract WebP file(s) to files given by the output format"
  results = []
  for image_index, image in enumerate(images):
    # TODO: add extra fields if desired
    bounds = image.getbbox()
    width, height = bounds[2], bounds[3]
    kwds = {
      "index": image_index,
      "frame": image_index,
      "n": image_index + 1,
      "w": width,
      "width": width,
      "h": height,
      "height": height
    }
    image_filename = format_extract_filename(oformat, image_index+1, **kwds)
    image.save(image_filename)
    logger.debug("Generated {}".format(image_filename))
    results.append(image_filename)
  return results

def main():
  # pylint: disable=missing-function-docstring
  ap = argparse.ArgumentParser(
      formatter_class=argparse.RawDescriptionHelpFormatter,
      epilog="""
Input and output formats are deduced using filename extensions. The two common
modes of operation are:
  1) Split a WebP file into multiple frames
This is done if any input path ends in ".webp" or if the output path argument
is a format string.
  2) Combine multiple files into a WebP image
This is done if the output path ends in ".webp".
""")
  ap.add_argument("path", nargs="*", help="file(s) to process")
  ap.add_argument("-i", "--input", metavar="PATH",
      help="file containing a list of paths to process, one per line")
  ap.add_argument("-o", "--output", metavar="PATH",
      help="destination path (see below for usage)")
  ag = ap.add_argument_group()
  mg = ag.add_mutually_exclusive_group()
  mg.add_argument("-m", "--mode",
      choices=(MODE_CREATE, MODE_EXTRACT),
      help="explicitly configure execution mode rather than deducing")
  mg.add_argument("-c", "--create", action="store_const",
      dest="mode", const=MODE_CREATE, help="Shorthand for --mode=%(const)s")
  mg.add_argument("-e", "--extract", action="store_const",
      dest="mode", const=MODE_EXTRACT, help="Shorthand for --mode=%(const)s")
  ag = ap.add_argument_group("diagnostics")
  mg = ag.add_mutually_exclusive_group()
  mg.add_argument("-q", "--quiet", action="store_true",
      help="inhibit all logging output (except for fatal errors)")
  mg.add_argument("-w", "--warnings", action="store_true",
      help="inhibit all logging output (except for warnings and errors)")
  mg.add_argument("-v", "--verbose", action="store_true",
      help="output diagnostic information")
  args = ap.parse_args()
  if args.quiet:
    logger.setLevel(logging.ERROR)
  if args.warnings:
    logger.setLevel(logging.WARN)
  if args.verbose:
    logger.setLevel(logging.DEBUG)
    logger.debug(args)

  paths = gather_inputs(args.path, args.input)
  if not paths:
    ap.error("Nothing to process; exiting")
  logger.debug("Scanning %d file(s)", len(paths))

  images = load_images(paths)
  mode = args.mode
  if mode is None:
    mode = deduce_mode(paths, args.output)
  
  if mode == MODE_CREATE:
    opath = deduce_create_output(args.output)
    logger.info("Creating WebP file {}".format(opath))
    create_webp_file(images, opath, fps=args.fps)
  elif mode == MODE_EXTRACT:
    oformat = deduce_extract_output(args.output)
    logger.info("Extracting WebP frames to {}".format(oformat))
    extract_webp_file(images, oformat)
  elif mode == MODE_ENCODE:
    if not args.output:
      ap.error("This mode requires an output path")
    if os.path.isdir(args.output):
      ap.error("{}: is a directory".format(args.output))
    write_video(paths, args.output, fps=args.fps)
  else:
    ap.error("Failed to deduce mode; please specify")

if __name__ == "__main__":
  main()

# vim: set ts=2 sts=2 sw=2: