#!/usr/bin/env python

"""
Montage a video file into a collage of equally-spaced frames.
"""

# TODO/FIXME:
# *) Allow user to configure paths to ffmpeg, ffprobe
# *) Allow user to select avconv over ffmpeg
# *) Add overwrite pre-check and configuration so ffmpeg/avconv doesn't prompt
#    for user input and error when user selects N.

import argparse
import errno
import json
import logging
import os
import pprint
import subprocess
import sys

class VideoError(Exception):
  def __init__(self, cause):
    super(VideoError, self).__init__(cause)
  def __str__(self):
    return "Video error: " + super(VideoError, self).__str__()
  def __repr__(self):
    return "VideoError({})".format(super(VideoError, self).__repr__())

COLOR_ADAPTER_DEFAULT_COLORS = {
  logging.DEBUG: '0',
  logging.INFO: '0',
  logging.WARNING: '1;33',
  logging.ERROR: '1;31',
  logging.CRITICAL: '1;31'
}

logger = None

class ColorFormatter(logging.Formatter):
  "Logging formatter to print records in color"
  def __init__(self, *args, **kwargs):
    self.__color_table = kwargs.get("colors", COLOR_ADAPTER_DEFAULT_COLORS)
    super(ColorFormatter, self).__init__(*args, **kwargs)

  def format(self, record):
    color = self.__color_table.get(record.levelno, "")
    if color is not None and color != "":
      record.levelname = "\033[{}m{}\033[0m".format(color, record.levelname)
    return super(ColorFormatter, self).format(record)

def format_timestamp(sec):
  "Convert seconds (int, float) to a timestamp HH:MM:SS string"
  frac = 0
  if sec != int(sec):
    frac = sec - int(sec)
  sec = int(sec)
  ns = sec % 60
  nm = sec // 60 % 60
  nh = sec // 60 // 60 % 60
  ret = "{:02}:{:02}:{:02}".format(nh, nm, ns)
  return ret

def is_number(n):
  "Return True if the value can be parsed as a float"
  try:
    float(n)
    return True
  except ValueError as _:
    return False

def format_bytes(size):
  "Format a number of bytes as a string"
  names = ("B", "KB", "MB", "GB", "TB")
  mag = 0
  while size > 1024:
    mag += 1
    size = size / 1024.0
  return "{} {}".format(round(size, 2), names[mag])

def _parse_frame_rate(fr):
  "Convert '<num>/<num>' frame-rate to a float"
  if fr.count("/") == 1:
    fn, fd = map(float, fr.split("/"))
  else:
    fn, fd = float(fr), 1
  if fd != 0:
    result = fn / fd
    logger.debug("Frame-rate {!r} -> {} fps".format(fr, result))
  else:
    result = None
    logger.debug("Frame-rate {!r} -> None; divide by zero".format(fr))
  return result

def _find_nb_frames(path):
  "Try (using mediainfo) to deduce the number of frames the video has"
  try:
    cmd = ["mediainfo", "--Inform=Video;%FrameCount%", path]
    fc_text = subprocess.check_output(cmd).decode().strip()
    logger.debug("%s yielded %r", subprocess.list2cmdline(cmd), fc_text)
    if is_number(fc_text):
      return fc_text
  except FileNotFoundError:
    logger.info("mediainfo does not appear to be installed")
  except subprocess.CalledProcessError as e:
    logger.error("mediainfo failed:")
    logger.exception(e)

def _fixup_probe(path, vformat, vstreams):
  "Attempt to fix common issues with ffprobe output"
  if "size" not in vformat:
    vformat["size"] = f"{os.stat(path).st_size}"
  for snr, stream in enumerate(vstreams):
    if stream.get("codec_type") == "video":
      if "nb_frames" not in stream:
        logger.debug("%s stream %d: get nb_frames via mediainfo...", path, snr)
        fc = _find_nb_frames(path)
        if fc is not None:
          stream["nb_frames"] = fc
      if "nb_frames" not in stream:
        logger.debug("%s stream %d: get nb_frames...", path, snr)
        duration = stream.get("duration", vformat.get("duration"))
        if duration is not None and is_number(duration):
          dsec = float(duration)
          afr = stream.get("avg_frame_rate")
          if afr is not None and afr != "0/0":
            fr = _parse_frame_rate(afr)
            if fr is not None:
              stream["nb_frames"] = f"{int(dsec * fr)}"
      # If the above failed, store -1
      if "nb_frames" not in stream:
        stream["nb_frames"] = "-1"
  return vformat, vstreams

def probe_video(path, **kwargs):
  "Probe <path> and return pair of <file-info>, <stream-info> dicts"
  cmd = ["ffprobe", "-show_format", "-show_streams", "-of", "json", "-v", "error"]
  cmd.append(path)
  logger.debug("Running {}".format(subprocess.list2cmdline(cmd)))
  vdata = json.loads(subprocess.check_output(cmd))
  vformat, vstreams = _fixup_probe(path, vdata["format"], vdata["streams"])
  vstream = None
  logger.debug("vdata %s: %s", path, pprint.pformat(vdata))
  for snr, s in enumerate(vstreams):
    if s.get("codec_type") == "video":
      logger.debug("stream %d: %s", snr, pprint.pformat(s))
      if s.get("nb_frames", "X").isdigit():
        vstream = s
        # No break so we get the last one
  if vstream is None:
    logger.debug("vdata: %r", vdata)
    raise VideoError("Failed to probe {!r}; no video stream found".format(path))
  return vformat, vstream

def extract_video_info(fdata, sdata):
  "Merge format and stream data into a single object"
  data = {
    "frames": None,
    "width": sdata["width"],
    "height": sdata["height"],
    "start_time": sdata["start_time"]
  }

  # Determine duration
  if sdata.get("duration", "N/A") != "N/A":
    data["duration"] = sdata["duration"]
  elif fdata.get("duration", "N/A") != "N/A":
    data["duration"] = fdata["duration"]
  else:
    raise VideoError(ValueError("Can't find duration from fdata={} sdata={}".format(fdata, sdata)))

  # Determine frame count
  if "nb_frames" in sdata:
    data["frames"] = sdata["nb_frames"]
  elif "duration" in fdata and "avg_frame_rate" in sdata:
    afr = sdata["avg_frame_rate"]
    fn, fd = "0", "1"
    if is_number(afr):
      fn = afr
    elif afr.count("/") == 1:
      fn, fd = afr.split("/")
    if fd != "0":
      d = float(fdata["duration"])
      fr = float(fn) / float(fd)
      data["frames"] = d * fr

  if data.get("frames") is None:
    # Didn't find the frame count
    raise VideoError(ValueError("Can't get frame count from fdata={} sdata={}".format(fdata, sdata)))

  return data

def montage(inpath, outpath, nr, nc, **kwargs):
  """
  Read <inpath> and write a collage of equally-distributed frames to <outpath>.
  The collage is <nr> rows by <nc> columns. Each frame is taken equal distances
  apart, where possible.

  Keyword arguments:
    ffquiet: boolean: decrease ffmpeg's output
    ffargs: list: arguments to pass to ffmpeg
    ffiargs: list: arguments to pass to ffmpeg, before -i
    ffoargs: list: arguments to pass to ffmpeg, after input path argument
    text: boolean: if True, add textual information to the resulting image
    size: (int, int): force final image to be this size
    scale: float: scale frames by a value 0..1 before composing
  """
  # Figure out the configuration
  ffquiet = kwargs.get("ffquiet", False)
  ffargs = kwargs.get("ffargs", None)
  ffiargs = kwargs.get("ffiargs", None)
  ffoargs = kwargs.get("ffoargs", None)
  text = kwargs.get("text", False)
  size = kwargs.get("size", None)
  scale = kwargs.get("scale", None)

  # Examine the video and calculate various necessary things
  fdata, sdata = probe_video(inpath) # TODO: add kwargs
  data = extract_video_info(fdata, sdata)
  w, h = int(data["width"]), int(data["height"])
  nf = int(data["frames"])
  sts = format_timestamp(float(data["start_time"]))
  ets = format_timestamp(float(data["duration"]))
  logger.debug(f"Size: w={w} h={h}")
  logger.debug(f"Frames: {nf}")
  logger.debug(f"Start timestamp: {sts}")
  logger.debug(f"Ending timestamp: {ets}")
  logger.debug(f"Frame selection interval: {nr*nc} over {nf} frames")
  logger.debug(f"Frame selection interval: one each {nf//(nr*nc)} frames")

  # Calculate frame width and height
  fw, fh = w, h
  if size is not None:
    if size[0] is not None:
      fw = round(float(size[0]) / nc)
    if size[1] is not None:
      fh = round(float(size[1]) / nr)
    if size[0] is None and size[1] is not None:
      # Calculate w based on h
      fw = float(fh) / h * w
    elif size[0] is not None and size[1] is None:
      # Calculate h based on w
      fh = float(fw) / w * h
  if scale is not None:
    fw = w * scale
    fh = h * scale

  # Build the ffmpeg command line
  logger.info("filesize: {}".format(format_bytes(os.stat(inpath).st_size)))
  logger.info("isize: {}x{}, osize={}x{}".format(w, h, fw, fh))
  logger.info("frames: {} ({} to {})".format(nf, sts, ets))
  func = "not(mod(n\\,{}))".format(nf // (nr * nc))
  expr = "select={},scale={}:{},tile={nc}x{nr}".format(func, fw, fh, nr=nr, nc=nc)
  cmd = ["ffmpeg", "-ss", sts]
  if ffiargs is not None:
    cmd.extend(ffiargs)
  cmd.extend(["-i", inpath])
  if ffoargs is not None:
    cmd.extend(ffoargs)
  cmd.extend(["-frames", "1", "-vf", expr, outpath])
  if ffquiet:
    cmd.extend(["-v", "warning"])
  if ffargs is not None:
    cmd.extend(ffargs)
  logger.info("Running {}".format(subprocess.list2cmdline(cmd)))
  if not kwargs.get("dry", False):
    subprocess.check_call(cmd)
  else:
    logger.info("Dry run; not executing {}".format(subprocess.list2cmdline(cmd)))

  # Overlay text if requested
  if text:
    lines = []
    lines.append(ets)
    lines.append(format_bytes(os.stat(inpath).st_size))
    tstr = "\n".join(lines)
    logger.info("Embedding the following text:\n{}".format(tstr))
    fgtext_file = ".temp-{}-{}.txt".format(os.path.basename(outpath), os.getpid())
    open(fgtext_file, "w").write(tstr)
    fgraph = "drawtext=font=Sans:fontsize=18:textfile={}:x=1:y=1".format(fgtext_file)
    cmd = ["ffmpeg", "-i", outpath, "-filter_complex", fgraph, outpath + "-2.png"]
    if ffquiet:
      cmd.extend(["-v", "warning"])
    if ffargs is not None:
      cmd.extend(ffargs)
    logger.info("Running {}".format(subprocess.list2cmdline(cmd)))
    if not kwargs.get("dry", False):
      subprocess.check_call(cmd)
      os.rename(outpath + "-2.png", outpath)
    else:
      logger.info("Dry run; not executing {}".format(subprocess.list2cmdline(cmd)))
    os.unlink(fgtext_file)

def main():
  global logger
  # Arguments after -- are passed to ffmpeg
  ffargs = []
  if "--" in sys.argv:
    ffargs = sys.argv[sys.argv.index("--")+1:]
    sys.argv = sys.argv[:sys.argv.index("--")]
  ap = argparse.ArgumentParser(epilog="""
By default, if -o,--out is not specified, output filename will be the input
filename with ".png" appended. If -o,--out is a directory, then the generated
files will be placed inside it. It is an error to pass multiple inputs and pass
a filename to -o,--out.
  """)
  ap.add_argument("path", nargs="+",
                  help="video file(s) to montage")
  ap.add_argument("-I", "--iarg", metavar="ARG", action="append",
                  help="pass ARG to ffmpeg (before -i) (can be used more than once)")
  ap.add_argument("-O", "--oarg", metavar="ARG", action="append",
                  help="pass ARG to ffmpeg (after -i) (can be used more than once)")
  ap.add_argument("-o", "--out", metavar="PATH",
                  help="output montage image path (default: input.png)")
  ap.add_argument("-r", "--rows", type=int, default=3, metavar="N",
                  help="number of rows (default: %(default)s)")
  ap.add_argument("-c", "--cols", type=int, default=4, metavar="N",
                  help="number of cols (default: %(default)s)")
  ap.add_argument("-s", "--scale", type=float, metavar="P",
                  help="scale frames by an amount between 0 and 1")
  ap.add_argument("-W", "--width", type=int, metavar="N",
                  help="force output to be N pixels wide")
  ap.add_argument("-H", "--height", type=int, metavar="N",
                  help="force output to be N pixels tall")
  ap.add_argument("-t", "--text", action="store_true",
                  help="overlay text onto the output")
  ap.add_argument("-n", "--no-overwrite", action="store_true",
                  help="skip entries that would overwrite files")
  ap.add_argument("-C", "--continue-on-error", action="store_true",
                  help="continue even if ffmpeg/avconv fails")
  ap.add_argument("-N", "--no-color", action="store_true",
                  help="do not use color when logging")
  ap.add_argument("--dry", action="store_true",
                  help="print what would be done without doing it")
  ap.add_argument("-v", "--verbose", action="store_true",
                  help="output more stuff")
  ap.add_argument("--ffquiet", action="store_true",
                  help="tell ffmpeg to be quieter")
  args = ap.parse_args()
  if not args.no_color:
    logging_format = "%(module)s:%(lineno)s:%(levelname)s: %(message)s"
    formatter = ColorFormatter(logging_format, None)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)
  else:
    logging_format = "%(module)s:%(lineno)s:%(levelname)s: %(message)s"
    logging.basicConfig(format=logging_format, level=logging.INFO)
  logger = logging.getLogger("avmontage")
  if args.verbose:
    logger.setLevel(logging.DEBUG)
  if args.scale is not None and (args.width is not None or args.height is not None):
    ap.error("--scale and --width,--height are mutually exclusive")
  if len(args.path) > 1:
    if args.out is not None and not os.path.isdir(args.out):
      ap.error("more than one file: --out must be omitted or a directory")

  if len(ffargs) > 0:
    logger.info("Extracted ffargs {}".format(subprocess.list2cmdline(ffargs)))
    logger.info("Remaining sys.argv: {}".format(sys.argv))

  count = len(args.path)
  for idx, path in enumerate(args.path):
    logger.info("{}/{}: {!r}".format(idx+1, count, path))
    if not os.path.exists(path):
      ap.error("\"{}\": no such file".format(path))
    out = "{}.png".format(path)
    if args.out is not None:
      out = os.path.join(args.out, out) if os.path.isdir(args.out) else args.out
    if os.path.exists(out):
      if args.no_overwrite:
        logger.warn("File {!r} exists; skipping {!r}".format(out, path))
        continue
      # ffmpeg/avconv will prompt the user for overwriting
    margs = (path, out, args.rows, args.cols)
    mkwargs = {}
    mkwargs["ffquiet"] = not args.verbose or args.ffquiet
    mkwargs["ffargs"] = ffargs
    mkwargs["text"] = args.text
    if args.iarg is not None:
      mkwargs["ffiargs"] = args.iarg
    if args.oarg is not None:
      mkwargs["ffoargs"] = args.oarg
    if args.width is not None or args.height is not None:
      mkwargs["size"] = (args.width, args.height)
    if args.scale is not None:
      mkwargs["scale"] = args.scale
    if args.dry is not None:
      mkwargs["dry"] = args.dry
    logger.debug("montage(*{}, **{})".format(margs, mkwargs))
    try:
      montage(*margs, **mkwargs)
    except (VideoError, subprocess.CalledProcessError) as e:
      logger.error("Fatal error while parsing {}".format(repr(path)))
      logger.error(str(e))
      if not args.continue_on_error:
        raise

if __name__ == "__main__":
  main()
else:
  logging_format = "%(module)s:%(lineno)s:%(levelname)s: %(message)s"
  logging.basicConfig(format=logging_format, level=logging.INFO)
  logger = logging.getLogger(__name__)

# vim: set ts=2 sts=2 sw=2:
