#!/usr/bin/env python3

"""
Functions to assist debugging within the pytest cases.
"""

import inspect
import logging
import os
import shlex
import subprocess
import sys

logging.basicConfig(format="%(module)s:%(lineno)s: %(levelname)s: %(message)s",
                    level=logging.INFO)
logger = logging.getLogger(__name__)

def getLogger():
  return logger

# TODO:
# Implement proper logging using pytest's APIs

def term_file():
  "Open a file descriptor referring to the containing terminal"
  try:
    return open("/dev/tty", "wt")
  except (IOError, OSError) as e:
    sys.stderr.write(
        f"{e}: Failed to obtain a file descriptor for the terminal;"
        f" using devnull {os.devnull!r}\n")
    return open(os.devnull, "wt")

def inspect_object(obj, color=False, indent=0):
  "Performs a crude inspection of an object and returns a string"
  items = []
  istr = " "*indent
  for k in dir(obj):
    if not k.startswith("_") and k not in ('f_builtins', 'f_globals'):
      key = k
      val = repr(getattr(obj, k))
      if color:
        key = f"\x1b[1;34m{key}\x1b[0m"
        val = f"\x1b[3;33m{val}\x1b[0m"
      items.append(f"{istr}{key}={val}")
  return "\n".join(items)

def caller(adjust=1):
  "Return the calling frame (adjusted by the given depth)"
  f = inspect.currentframe().f_back
  while adjust > 0 and f.f_back is not None:
    adjust -= 1
    f = f.f_back
  return f

def _debug_write(finfo, fobj, msg, prefix):
  "Write frame info, prefix, and msg to fobj"
  f_file = os.path.relpath(finfo.filename)
  fobj.write(f"{f_file}:{finfo.function}:{finfo.lineno}: ")
  if len(prefix) > 0:
    fobj.write(prefix)
  fobj.write(repr(msg) if not isinstance(msg, str) else msg)
  fobj.write("\n")

def debug_write(msg, prefix="DEBUG: "):
  "Output a debugging message"
  c = inspect.getframeinfo(caller())
  _debug_write(c, sys.stdout, msg, prefix)

def write_to_terminal(msg, prefix="INFO: "):
  "Output a message to the terminal, bypassing pytest entirely"
  c = inspect.getframeinfo(caller())
  with term_file() as fobj:
    _debug_write(c, fobj, msg, prefix)

def shell(cmd):
  "Execute command, sending stdout and stderr directly to the terminal"
  with term_file() as fobj:
    subprocess.check_call(shlex.split(cmd), stdout=fobj, stderr=fobj)

# vim: set ts=2 sts=2 sw=2:
