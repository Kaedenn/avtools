#!/usr/bin/env python

"""
Obtain information about a video file. Can be used as either a module or a
standalone script.

Depends on having ffprobe. Use -e,--exe to specify the path to avprobe, if
desired.

Script is designed to work with both Python 2.7 and 3.6+.

Support for mediainfo planned.
"""

# TODO: Incorporate mediainfo

import argparse
import json
import logging
import numbers
import os
import pprint
import subprocess
import sys

LOGGING_FORMAT = "%(filename)s:%(lineno)s:%(levelname)s: %(message)s"
logging.basicConfig(format=LOGGING_FORMAT, level=logging.WARNING)
logger = logging.getLogger(__name__)

PROBE_LOG_LEVELS = (
  "quiet", "panic", "fatal", "error", "warning", "info", "verbose", "debug")

PROBE_COMMAND = "ffprobe"

FORMAT_KINDS = []
def _add_format_kind(value):
  FORMAT_KINDS.append(value)
  return value
FORMAT_JSON = _add_format_kind("json")
FORMAT_JSON_PRETTY = _add_format_kind("json-pretty")
FORMAT_PYTHON = _add_format_kind("python")
FORMAT_KV = _add_format_kind("kv")
FORMAT_SUMMARY = _add_format_kind("summary")
del _add_format_kind

STREAM_AUDIO = "a"
STREAM_VIDEO = "v"
STREAM_OTHER = "o"
STREAM_ALL = STREAM_AUDIO + STREAM_VIDEO + STREAM_OTHER

def _check_output(args, env=None, **kwargs):
  "Run a program and return its output"
  pkwargs = {}
  cmdline = subprocess.list2cmdline(args)
  logger.debug("Executing {!r}".format(cmdline))
  if kwargs:
    pkwargs.update(kwargs)
  if env is not None and len(env) > 0:
    penv = dict(os.environ)
    penv.update(env)
    pkwargs["env"] = penv
    logger.debug("Passing env={!r}".format(env))
  if pkwargs:
    logger.debug("Passing kwargs={!r}".format(pkwargs))
  output = subprocess.check_output(args, **pkwargs)
  logger.debug("Read {} bytes from {!r}".format(len(output), cmdline))
  return output

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

def to_float(s):
  "Convert s to a float or NaN if s is N/A"
  if s == "N/A" or s is None:
    return float("NaN")
  return float(s)

def format_duration(num_seconds):
  "Format a number of seconds like {}h{}m{}.{}s"
  if not isinstance(num_seconds, numbers.Number):
    num_seconds = float(num_seconds)
  unit, frac = int(num_seconds), float(num_seconds) - int(num_seconds)
  nhours = unit // 60 // 60
  nmins = (unit // 60) % 60
  nsecs = unit % 60
  nmsec = int(round(1000 * frac))
  hours = "{:d}".format(nhours)
  minutes = "{:02d}".format(nmins)
  seconds = "{:02d}".format(nsecs)
  if nmsec > 0:
    seconds += ".{:03d}".format(nmsec)
  if hours != "0":
    return "{}h{}m{}s".format(hours, minutes, seconds)
  elif minutes != "00":
    return "{}m{}s".format(minutes, seconds)
  else:
    return "{}s".format(seconds)

def format_bytes(size, format="{}{}", places=2):
  "Format a number of bytes to <places> decimal places"
  curr = size
  if not isinstance(size, numbers.Number):
    curr = float(size)
  bases = ["B", "KB", "MB", "GB", "TB"]
  base = 0
  while curr > 1024 and base+1 < len(bases):
    curr /= 1024.0
    base += 1
  return format.format(round(curr, places), bases[base])

def probe(path, program=PROBE_COMMAND, log_level="error", color=True,
    probe_input_args=(), probe_output_args=(), probe_env=None,
    probe_extra_args=None, fix_data=True,
    *args, **kwargs):
  """Generate a dict of the following information:
    "format": {video format information},
    "audio_streams": [{audio stream information}, ...],
    "video_streams": [{video stream information}, ...],
    "other_streams": [{other (subtitle, etc) stream information}, ...]
  `format` is a dict of format information returned by PROBE.
  `audio_streams` is a list of dicts, one for each audio stream.
  `video_streams` is a list of dicts, one for each video stream.
  `other_streams` is a list of dicts, one for each stream that isn't an
  audio stream or a video stream. This includes things like subtitles,
  annotations, etc.

  This function is designed to operate on the output of either avprobe or
  ffprobe and cannot parse arbitrary data, such as from mediainfo.

  `program` is the program to run: either avprobe or ffprobe. This argument can
  be used to specify custom builds/installations or for requesting avconv
  over ffmpeg. Default value is set by PROBE_COMMAND.

  `log_level` is the logging level to pass to PROBE. See PROBE_LOG_LEVELS
  for a list of valid values. Default value is "error".

  Setting `color` to False will disable color output for PROBE. This
  works by passing AV_LOG_FORCE_NOCOLOR=1 to the program.

  `probe_input_args` is a tuple of arguments to pass to PROBE. These
  arguments are inserted before the path argument.

  `probe_output_args` is a tuple of arguments to pass to PROBE. These
  arguments are inserted after the path argument.

  `probe_env` is a dict of environment variables to pass to PROBE.

  If `fix_data` is True, then various items are parsed as appropriate
  (duration, frame-rate, etc. all converted to decimals, missing values
  interpreted, etc.).
  """
  # Generate command line and arguments to pass to subprocess
  cmd = [program, "-show_format", "-show_streams", "-of", "json"]
  if log_level in PROBE_LOG_LEVELS:
    cmd.extend(("-v", log_level))
  if probe_input_args:
    cmd.extend(probe_input_args)
  cmd.append(path)
  if probe_output_args:
    cmd.extend(probe_output_args)

  penv = {}
  # Disable color output if desired
  if not color:
    penv["AV_LOG_FORCE_NOCOLOR"] = "1"
  # probe() parameters can override AV_LOG_FORCE_NOCOLOR
  if probe_env is not None:
    penv.update(probe_env)

  # Invoke avprobe/ffprobe and parse the output as JSON
  vdata = json.loads(_check_output(cmd, env=penv))
  logger.debug("Output from probe: {!r}".format(vdata))

  # Parse the output into a usable format
  info = {
    "format": vdata["format"],
    "audio_streams": [],
    "video_streams": [],
    "other_streams": []
  }
  for stream in vdata["streams"]:
    if stream["codec_type"] == "audio":
      info["audio_streams"].append(stream)
    elif stream["codec_type"] == "video":
      info["video_streams"].append(stream)
    else:
      info["other_streams"].append(stream)

  if "size" not in info["format"]:
    info["format"]["size"] = os.stat(path).st_size

  # Ensure certain values are present and have expected types
  if fix_data:
    fixup_streams = [info["format"]]
    fixup_streams.extend(info["video_streams"])
    fixup_streams.extend(info["audio_streams"])
    for stream in fixup_streams:
      if "size" in stream and stream["size"] != "unknown":
        stream["size"] = int(to_float(stream["size"]))
      if "duration" in stream:
        stream["duration"] = to_float(stream["duration"])
      if "start_time" in stream:
        stream["start_time"] = to_float(stream["start_time"])
      if "bit_rate" in stream:
        stream["bit_rate"] = to_float(stream["bit_rate"])
      if "sample_rate" in stream:
        stream["sample_rate"] = to_float(stream["sample_rate"])
      if "nb_frames" not in stream:
        logger.debug("nb_frames not present, calculating from duration...")
        duration = stream.get("duration", info["format"].get("duration"))
        if duration is not None:
          afr = stream.get("avg_frame_rate", "0/0")
          if afr is not None and afr != "0/0":
            f = _parse_frame_rate(afr)
            if f is not None:
              stream["nb_frames"] = to_float(duration) * f
      # If the above failed, place -1 in nb_frames
      if "nb_frames" not in stream:
        stream["nb_frames"] = -1

  return info

def _main_once(path, args):
  "Perform everything main() would do, on a single path"
  # Probe the file with the given configuration and return the resulting data
  file_info = probe(path,
      program=args.exe,
      log_level=args.log_level,
      color=not args.no_color,
      probe_input_args=args.iargs,
      probe_output_args=args.oargs,
      fix_data=not args.raw_data)

  # Add path and name keys
  vf = file_info["format"]
  vf["path"] = os.path.abspath(vf.get("filename", path))
  vf["name"] = os.path.basename(vf["path"])

  def _purge_stream_info(sname):
    "Remove named stream 'audio', 'video', or 'other' from file_info"
    skey = "{}_streams".format(sname)
    if skey in file_info:
      sdata = file_info[skey]
      logger.debug("Removing {} stream data {!r}".format(sname, sdata))
      del file_info[skey]
    else:
      logger.warning("Removing stream {}: data not present".format(sname))

  # Purge unwanted streams from the data
  if STREAM_AUDIO not in args.streams:
    _purge_stream_info("audio")
  if STREAM_VIDEO not in args.streams:
    _purge_stream_info("video")
  if STREAM_OTHER not in args.streams:
    _purge_stream_info("other")

  # Output the data using the requested format
  if args.format in (FORMAT_JSON, FORMAT_JSON_PRETTY):
    json_args = {}
    if args.format == FORMAT_JSON_PRETTY:
      json_args["indent"] = 2
      json_args["sort_keys"] = True
    print(json.dumps(file_info, **json_args))
  elif args.format == FORMAT_PYTHON:
    print(repr(file_info))
  elif args.format == FORMAT_KV:
    for k, v in file_info["format"].items():
      print("format.{} = {}".format(k, json.dumps(v)))
    for idx, stream in enumerate(file_info.get("audio_streams", ())):
      for k, v in stream.items():
        print("audio.{}.{} = {}".format(idx, k, json.dumps(v)))
    for idx, stream in enumerate(file_info.get("video_streams", ())):
      for k, v in stream.items():
        print("video.{}.{} = {}".format(idx, k, json.dumps(v)))
    for idx, stream in enumerate(file_info.get("other_streams", ())):
      for k, v in stream.items():
        print("other.{}.{} = {}".format(idx, k, json.dumps(v)))
  elif args.format == FORMAT_SUMMARY:
    format_info = file_info["format"]
    vpath = os.path.relpath(format_info["path"])
    vformat = format_info.get("format_long_name")
    if vformat is None:
      # Intentionally propagate KeyError
      vformat = format_info["format_name"]
    vdur = format_info.get("duration")
    vsize = format_info.get("size")
    vsdur = "None" if vdur is None else format_duration(vdur)
    vssize = "None" if vsize is None else format_bytes(vsize, format="{} {}")
    print("{path}: {format}".format(path=vpath, format=vformat))
    print("  duration: {dur}".format(dur=vsdur))
    print("  file size: {size}".format(size=vssize))
    if len(file_info["video_streams"]) > 0:
      vs0 = file_info["video_streams"][0]
      vw = vs0["width"]
      vh = vs0["height"]
      print("  video image size: {}x{}px".format(vw, vh))
    if len(file_info["audio_streams"]) > 0:
      as0 = file_info["audio_streams"][0]
      print("  audio channels: {}".format(as0["channels"]))


def main():
  ap = argparse.ArgumentParser(
      formatter_class=argparse.RawDescriptionHelpFormatter,
      epilog="""
"PROBE" refers to either avprobe or ffprobe, depending on -e,--exe.

-e,--exe can be used to pick which PROBE executable to use (avprobe/ffprobe).
-I,--iargs options are inserted before the path in the PROBE command-line.
-O,--oargs options are inserted after the path in the PROBE command-line.
-s,--streams takes one or more stream selection letters. For example, use "av"
  to select audio and video streams, "v" to select just video streams, or "x"
  to omit all streams and output only the top-level format information.
-f,--format options have the following behavior:
  "json-pretty": print the output as a JSON-encoded object with two-space
    indentation and sorted keys.
  "json": print the output as a JSON-encoded object. No special formatting or
    indenting is done.
  "python": print the Python repr() of the object. No special formatting or
    indenting is done.
  "kv": print a list of keys and values describing the object. <stream#> refers
    to the stream's numeric index, starting at 0. All values are JSON-encoded.
    Lines will have one of the following formats:
      General (top-level) format keys: "format.<key> = <value>"
      Audio stream keys: "audio.<stream#>.<key> = <value>"
      Video stream keys: "video.<stream#>.<key> = <value>"
      Other stream keys: "other.<stream#>.<key> = <value>"

Unless --raw-data is specified, the following "fixes" are performed on all
streams returned by PROBE:
  "size", if present and not "unknown", is converted to an integer.
  "duration", if present, is converted to a floating-point number.
  "start_time", if present, is converted to a floating-point number.
  "bit_rate", if present, is converted to a floating-point number.
  "sample_rate", if present, is converted to a floating-point number.
  "nb_frames", if not present, is deduced by dividing the duration by the
    average frame-rate. If this fails (or the average frame-rate is unknown or
    "0/0"), then nb_frames is set to -1.
Note that these "fix-ups" alter the types of these fields and can break
downstream programs depending on these values being numeric.

Passing multiple values to PATH is equivalent to running this program on each
path separately. No special formatting is done for multiple paths.
  """)
  ap.add_argument("path", nargs="+", help="path(s) to analyze")
  ap.add_argument("-e", "--exe", default=PROBE_COMMAND,
      help="probe executable (default: %(default)s)")
  ap.add_argument("-l", "--log-level", choices=PROBE_LOG_LEVELS,
      default="error",
      help="logging level for the probe executable (default: %(default)s)")
  ap.add_argument("-I", "--iargs", action="append",
      help="input arguments for probe executable")
  ap.add_argument("-O", "--oargs", action="append",
      help="output arguments for probe executable")
  ap.add_argument("-s", "--streams", default=STREAM_ALL,
      help="stream selection (a=audio, v=video, o=other, x=none)"
           " (default: %(default)s)")
  ap.add_argument("-C", "--no-color", action="store_true",
      help="disable color output")
  ap.add_argument("--raw-data", action="store_true",
      help="do not attempt to 'fix' probed data")

  ag = ap.add_argument_group("output format")
  mg = ag.add_mutually_exclusive_group()
  mg.add_argument("-f", "--format", choices=FORMAT_KINDS, default=FORMAT_JSON,
      help="output format (default: %(default)s)")
  mg.add_argument("-J", "--json", dest="format", const=FORMAT_JSON_PRETTY,
      action="store_const", help="alias for -f %(const)s")
  mg.add_argument("-P", "--py", dest="format", const=FORMAT_PYTHON,
      action="store_const", help="alias for -f %(const)s")
  mg.add_argument("-K", "--kv", dest="format", const=FORMAT_KV,
      action="store_const", help="alias for -f %(const)s")
  mg.add_argument("-S", "--sum", dest="format", const=FORMAT_SUMMARY,
      action="store_const", help="alias for -f %(const)s")

  ag = ap.add_argument_group("diagnostics")
  ap.add_argument("-q", "--quiet", action="store_true",
      help="only output errors")
  ap.add_argument("-i", "--info", action="store_true",
      help="output informational messages")
  ap.add_argument("-v", "--verbose", action="store_true",
      help="output diagnostic messages")
  ap.add_argument("-d", "--debug", dest="verbose", action="store_true",
      help="output diagnostic messages (provided for symmetry for scripting)")
  args = ap.parse_args()

  if args.quiet:
    logger.setLevel(logging.ERROR)
  if args.info:
    logger.setLevel(logging.INFO)
  if args.verbose:
    logger.setLevel(logging.DEBUG)

  for path in args.path:
    _main_once(path, args)

if __name__ == "__main__":
  main()

# vim: set ts=2 sts=2 sw=2:
