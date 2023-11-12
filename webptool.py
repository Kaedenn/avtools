#!/usr/bin/env python3

"""
Create or split WebP images
"""

import argparse
import json
import logging
import os
import string
import subprocess
import sys

import webp
from PIL import Image
import cv2

logging.basicConfig(level=logging.INFO,
    format="%(module)s:%(lineno)s: %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MODE_DESCRIBE = "describe-webp"
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

def webpmux_info(path):
  "Run webpmux -info and sanitize the output"
  args = ["webpmux", "-info", path]
  logger.debug("Invoking %s", subprocess.list2cmdline(args))
  out = subprocess.check_output(args).decode()
  for lnr, line in enumerate(out.splitlines()):
    logger.debug("webpmux %s line %d: %s", path, lnr, line)
    if ":" not in line:
      if line != "No features present.":
        logger.warning("Can't parse line %r", line)
    elif line.count(":") == 1:
      lkey, lval = line.split(":")
      yield lkey.strip(), lval.strip()
    elif line.count(":") == 2:
      for field in line.split("  "):
        lkey, lval = field.split(":", 1)
        yield lkey.strip(), lval.strip()
    else:
      logger.warning("Unable to parse line %r", line)

def get_webp_info(path):
  "Get information about the WebP file"
  webpinfo = webpmux_info(path)
  results = {
    "size": (0, 0),
    "features": [],
    "bgcolor": 0,
    "loops": 0,
    "nframes": 0,
    "frames": [],
    "duration": None
  }
  fheaders = []
  for lkey, lval in webpinfo:
    lkey = lkey.lower()
    if not lval:
      logger.warning("key %s has no value", lkey)
    elif lkey == "canvas size":
      cxsize, cysize = lval.split(" x ")
      results["size"] = (int(cxsize), int(cysize))
    elif lkey == "features present":
      results["features"] = lval.split()
    elif lkey == "background color":
      if lval.startswith("0x"):
        lval = lval[2:]
      if lval:
        results["bgcolor"] = int(lval, 16)
      else:
        logger.warning("failed to parse bgcolor %s", lval)
    elif lkey == "loop count":
      results["loops"] = int(lval)
    elif lkey == "number of frames":
      results["nframes"] = int(lval)
    elif lkey == "no.":
      fheaders = lval.split()
    elif lkey.isdigit():
      fvalues = lval.split()
      if len(fvalues) != len(fheaders):
        logger.warning("Inconsistent frame data %r", lval)
        continue
      finfo = {"num": int(lkey)}
      for fvkey, fvval in zip(fheaders, fvalues):
        if fvval.isdigit():
          fvval = int(fvval)
        finfo[fvkey] = fvval
      if results["duration"] is None:
        results["duration"] = 0
      results["duration"] += finfo["duration"]
      results["frames"].append(finfo)
    elif lkey == "size of the xmp metadata":
      results["xmpsize"] = lval
    else:
      logger.warning("Failed to parse key %s value %r", lkey, lval)
  if results["nframes"] != len(results["frames"]):
    logger.warning("Inconsistent frame count (expect %d, got %d)",
        results["nframes"], len(results["frames"]))
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

def image_size(image):
  "Get the width and height of the image in pixels"
  isize = image.getbbox()
  return isize[2], isize[3]

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
    logger.warning("Unknown output path; using %s", DEFAULT_WEBP_NAME)
    return DEFAULT_WEBP_NAME
  if os.path.isdir(path_out):
    outpath = os.path.join(path_out, DEFAULT_WEBP_NAME)
    logger.warning("Output path is a directory; using %s", outpath)
    return outpath
  if not path_out.endswith(".webp"):
    logger.warning("Output path does not end in .webp; continuing anyway")
  return path_out

def deduce_extract_output(path_out):
  "Determine final output format for the extract mode"
  outpath = path_out
  if path_out is None:
    outpath = os.path.join(os.curdir, DEFAULT_NAME_FORMAT)
    logger.warning("Unknown output path; using %s", outpath)
  elif os.path.isdir(path_out):
    outpath = os.path.join(path_out, DEFAULT_NAME_FORMAT)
    logger.warning("Output path is a directory; using %s", outpath)
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

def describe_webp_file(path, *args, **kwargs):
  "Display information about a single WebP file"
  vinfo = get_webp_info(path)
  images = load_images([path])
  if not images:
    raise ValueError(f"failed to load images from {path}")

  # Determine real image size, ensure vinfo["size"] has it
  isizes = tuple(set(image_size(image) for image in images))
  isize = vinfo["size"]
  if not isizes:
    logger.warning("Could not get size of %s", path)
  elif len(isizes) > 1:
    logger.warning("%s has multiple sizes %r", path, isizes)
    iwidth = max(isize[0] for isize in isizes)
    iheight = max(isize[1] for isize in isizes)
    isize = (iwidth, iheight)
    logger.warning("%s: using size %s", path, isize)
  else:
    isize = isizes[0]
  if isize != vinfo["size"]:
    logger.warning("%s: inconsistent image size info=%r split=%r",
        path, vinfo["size"], isize)
    vinfo["size"] = (isize[0], isize[1])

  # Determine real frame count; ensure vinfo["nframes"] has it
  nframes = len(images)
  if nframes != vinfo["nframes"]:
    logger.warning("%s inconsistent frame count info=%d split=%d",
        path, vinfo["nframes"], nframes)
    vinfo["nframes"] = max(nframes, vinfo["nframes"])

  if kwargs.get("json"):
    jargs = {}
    if kwargs.get("indent"):
      jargs["sort_keys"] = True
      jargs["indent"] = kwargs["indent"]
    result = json.dumps(vinfo, **jargs)
    print(result)
  else:
    pl = "{} frame{}".format(len(images), "" if len(images) == 1 else "s")
    print("{}: {}".format(path, pl))
    isize = images[0].getbbox() # assume all images have the same size
    print("Size: {}x{}".format(isize[2], isize[3]))

def describe_webp_files(paths, *args, **kwargs):
  "Display information about WebP files"
  for path in paths:
    describe_webp_file(path, *args, **kwargs)

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
    logger.debug("Generated %s", image_filename)
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
  ag = ap.add_argument_group("mode")
  mg = ag.add_mutually_exclusive_group()
  mg.add_argument("-m", "--mode",
      choices=(MODE_DESCRIBE, MODE_CREATE, MODE_EXTRACT),
      help="explicitly configure execution mode rather than deducing")
  mg.add_argument("-d", "--describe", action="store_const",
      dest="mode", const=MODE_DESCRIBE, help="Shorthand for --mode=%(const)s")
  mg.add_argument("-c", "--create", action="store_const",
      dest="mode", const=MODE_CREATE, help="Shorthand for --mode=%(const)s")
  mg.add_argument("-e", "--extract", action="store_const",
      dest="mode", const=MODE_EXTRACT, help="Shorthand for --mode=%(const)s")
  ag = ap.add_argument_group("output")
  ag.add_argument("-j", "--json", action="store_true",
      help="format output as JSON")
  ag.add_argument("--indent", type=int,
      help="indent JSON with %(metavar)s spaces")
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

  mode = args.mode
  if mode is None:
    mode = deduce_mode(paths, args.output)

  if mode == MODE_DESCRIBE:
    describe_webp_files(paths, json=args.json, indent=args.indent)
    # for path in paths:
    #   vinfo = get_webp_info(path)
    #   logger.debug(vinfo)
    #   print("Features: {}".format(" ".join(vinfo["features"])))
    #   print("Background: {:08x}".format(vinfo["bgcolor"]))
    #   nloops = "infinite" if vinfo["loops"] == 0 else str(vinfo["loops"])
    #   print("Loops: {}".format(nloops))
    #   if vinfo["duration"] is not None and vinfo["duration"] > 0:
    #     fps = len(vinfo["frames"]) / (vinfo["duration"] / 1000)
    #     print("Duration: {}ms (~{:.02f}fps)".format(vinfo["duration"], fps))
    #   else:
    #     print("Duration: unknown")
    #   print("Frames: {}".format(len(vinfo["frames"])))
    #   for frame in vinfo["frames"]:
    #     print(("  {num:3d} {width}x{height}"
    #            " alpha={alpha:3s}"
    #            " offset=({x_offset},{y_offset})"
    #            " {duration:3d}ms"
    #            " blend={blend:3s}"
    #            " {image_size}b"
    #            " {compression}").format(**frame))
  elif mode == MODE_CREATE:
    images = load_images(paths)
    opath = deduce_create_output(args.output)
    logger.info("Creating WebP file %s", opath)
    create_webp_file(images, opath, fps=args.fps)
  elif mode == MODE_EXTRACT:
    images = load_images(paths)
    oformat = deduce_extract_output(args.output)
    logger.info("Extracting WebP frames to %s", oformat)
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
