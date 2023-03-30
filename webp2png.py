#!/usr/bin/env python3

"""
Convert a single-frame WebP file into a static image
"""

import argparse
import logging
import os

import webp

logging.basicConfig(level=logging.INFO,
    format="%(module)s:%(lineno)s: %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

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

def load_webp_image(path):
  "Load the first frame of the given WebP file"
  try:
    frames = webp.load_images(path)
    if not frames:
      raise ValueError(f"File {path!r} returned zero frames")
    if len(frames) > 1:
      logger.warning("%s has %d frames instead of 1", path, len(frames))
    return frames[0]
  except webp.WebPError as err:
    logger.error("%s while reading %s", err, path)
    raise err

def remap_ext(path, new_ext):
  "Replace the extension with the one given"
  ipart, iext = os.path.splitext(path)
  return os.path.extsep.join((ipart, new_ext))

def get_output_path(ipath, opath, ext="png"):
  "Determine the final output path"
  ibase = os.path.dirname(ipath)
  ifile = os.path.basename(ipath)
  if not opath:
    ofile = remap_ext(ifile, ext)
    opath = os.path.join(ibase, ofile)
    logger.info("Saving %s to %s", ipath, opath)
  elif opath[-1] in ("/", "\\") or os.path.isdir(opath):
    if not os.path.isdir(opath):
      logger.info("Creating directory %s", opath)
      os.makedirs(opath)
    ofile = remap_ext(ifile, ext)
    opath = os.path.join(opath, ofile)
  return opath

def convert_image(ipath, opath, ext="png", force=False):
  "Convert a single image"
  opath = get_output_path(ipath, opath, ext=ext)
  logger.debug("%s -> %s", ipath, opath)
  if os.path.exists(opath):
    if not force:
      logger.error("Can't convert %s: %s exists", ipath, opath)
      return False
    logger.warning("Converting %s: %s exists; overwriting", ipath, opath)
  image = load_webp_image(ipath)
  image.save(opath)
  return True

def main():
  # pylint: disable=missing-function-docstring
  ap = argparse.ArgumentParser(epilog="""
An error is generated if OPATH is given, is not a directory, and if more
than one file is specified.
""", formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("path", nargs="*", help="file(s) to process")
  ap.add_argument("-i", "--input", metavar="IPATH",
      help="file containing a list of paths to process, one per line")
  ap.add_argument("-o", "--output", metavar="OPATH",
      help="destination path (see below for usage)")
  ap.add_argument("-f", "--force", action="store_true",
      help="overwrite destination image if it exists")
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
  logger.debug("Processing %d file(s)", len(paths))

  for idx, path in enumerate(paths):
    logger.info("Processing %d/%d %s", idx+1, len(paths), path)
    convert_image(path, args.output, force=args.force)

if __name__ == "__main__":
  main()

# vim: set ts=2 sts=2 sw=2:
