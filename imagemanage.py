#!/usr/bin/env python3

"""
Display and manage a bunch of images.

Actions are printed when the program ends; program does not actually delete or
rename anything.
"""

# FIXME/TODO:
# Support SVG, XPM
# Support animated GIF files
# Calculate (instead of hard-coding) heights and adjusts (see TODOs below)
#   Calculate the size of the grid cell?
#   Calculate the sizes of the other grid cells?
#   Calculate the positions of the other grid cells and subtract?
# Provide some sort of interactive help (or just a message) for <Key-h>

import argparse
import collections
import csv
import datetime
import functools
import logging
import mimetypes
import os
import subprocess
import sys
import ttk
try:
  import tkinter as tk
except ImportError as e:
  import Tkinter as tk
import PIL.Image
import PIL.ImageTk

try:
  import tkFont
except ImportError as e:
  from tkinter import font as tkFont

LOGGING_FORMAT = "%(filename)s:%(lineno)s:%(levelname)s: %(message)s"
logging.basicConfig(format=LOGGING_FORMAT, level=logging.INFO)
logger = logging.getLogger(__name__)

SORT_MODES = ("none", "name", "time", "size", "rname", "rtime", "rsize")

SCALE_NONE = "none"
SCALE_SHRINK = "shrink"
SCALE_EXACT = "exact"

MODE_NONE = "none"
MODE_RENAME = "rename"
MODE_GOTO = "goto"
MODE_SET_IMAGE = "set-image"
MODE_COMMAND = "command"

INPUT_START_WIDTH = 20
SCREEN_WIDTH_ADJUST = 0
SCREEN_HEIGHT_ADJUST = 100 # TODO: Determine empirically

fromtimestamp = datetime.datetime.fromtimestamp

Asset = lambda f: os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "assets", f)

def format_size(nbytes, places=2):
  "Format a number of bytes"
  bases = ["B", "KB", "MB", "GB", "TB", "PB"]
  base = 0
  curr = nbytes
  while curr >= 1024 and base+1 < len(bases):
    curr /= 1024.0
    base += 1
  if places == 0:
    curr = int(curr)
  else:
    curr = round(curr, places)
  return "{} {}".format(curr, bases[base])

def iterate_from(item_list, start_index):
  "Iterate over an entire list, cyclically, starting at the given index + 1"
  curr = start_index + 1
  while curr < len(item_list):
    yield item_list[curr]
    curr += 1
  curr = 0
  while curr < start_index:
    yield item_list[curr]
    curr += 1
  yield item_list[start_index]

def debug(*args):
  "Display debug information about the given arguments"
  def _inspect(obj, pretty=False, indent=0):
    "Inspect one object"
    desc = {k: getattr(obj, k) for k in dir(obj) if k[:2] != "__"}
    if pretty and type(obj) not in (tuple, list, dict, str, int, float):
      sp = " "*indent
      return "\n".join("{}{} = {!r}".format(sp, k, v) for k,v in sorted(desc.items()))
    else:
      return repr(obj)
  for arg in args:
    name = "Event" if isinstance(arg, tk.Event) else type(arg).__name__
    logger.debug("{}({})".format(name, _inspect(arg, pretty=True, indent=2)))

def debug_call(func, *args, **kwargs):
  "Log and then call func(*args, **kwargs)"
  logger.debug("{}(*{}, **{})".format(func.__name__, args, kwargs))
  return func(*args, **kwargs)

def dump_functions(obj, func_prefix, omit=None):
  "DEBUGGING: Call all functions starting with a given prefix"
  print("Inspection of {}".format(repr(obj)))
  for key in dir(obj):
    if omit is not None and key in omit:
      continue
    if key.startswith(func_prefix):
      val = getattr(obj, key)
      if hasattr(val, "__call__"):
        try:
          print("  {}: {!r}".format(key, val()))
        except Exception as e:
          print("  {}".format(e))
      else:
        print("  {}: {!r}".format(key, val))

def blocked_by_input(func):
  "Block a function from being called if self._input has focus"
  @functools.wraps(func)
  def wrapper(self, *args, **kwargs):
    "Wrapper for the function whose input is to be blocked"
    if self._root.focus_get() == self._input:
      logger.debug("Input has focus; blocking event")
      return
    return func(self, *args, **kwargs)
  return wrapper

class ImageManager(object):
  """
  Display images and provide hotkeys to manage them. Does not actually rename
  or delete images.

  Use actions() to obtain the requested actions.

  Keyword arguments for __init__:
    width: total width of window, borders included
    height: total height of window, borders included
    show_text: if True, display image information in the upper-left corner
    input_width: width of input box (in characters)
    font_family: input and text font (default: monospace)
    font_size: input and text font size (default: 10)
    icon: path to an icon to use for the system tray
  """
  def __init__(self, images, **kwargs):
    self._root = root = tk.Tk()
    root.title("Image Manager") # Default; overwritten quite soon
    if kwargs.get("icon"):
      icon_image = PIL.Image.open(kwargs["icon"])
      root.iconphoto(False, PIL.ImageTk.PhotoImage(icon_image))

    # Bind to all relevant top-level events
    root.bind_all("<Key-Escape>", self.escape)
    root.bind_all("<Control-Key-w>", self.close)
    root.bind_all("<Key-Left>", self._prev_image)
    root.bind_all("<Key-Right>", self._next_image)
    root.bind_all("<Key-R>", self._rename_image)
    root.bind_all("<Key-D>", self._delete_image)
    root.bind_all("<Key-F>", self._find_image)
    root.bind_all("<Key-G>", self._go_to_image)
    root.bind_all("<Key-h>", self._show_help)
    root.bind_all("<Key-z>", self._adjust)
    root.bind_all("<Key-c>", self._adjust)
    root.bind_all("<Key-equal>", self._toggle_zoom)
    root.bind_all("<Key-slash>", self._enter_command)
    root.bind("<Configure>", self._update_window)
    for i in range(1, 10):
      root.bind_all("<Key-{}>".format(i), self._mark_image)

    # Configuration before widget construction
    self._width = kwargs.get("width", root.winfo_screenwidth()-SCREEN_WIDTH_ADJUST)
    self._height = kwargs.get("height", root.winfo_screenheight()-SCREEN_HEIGHT_ADJUST)
    self._enable_text = kwargs.get("show_text", False)
    self._input_width = kwargs.get("input_width", INPUT_START_WIDTH)
    self._text_functions = []
    self._scale_mode = SCALE_SHRINK

    # Configure fonts
    self._font_family = ff = kwargs.get("font_family", "monospace")
    self._font_size = fs = kwargs.get("font_size", 10)
    self._font = tkFont.Font(family=ff, size=fs)
    self._font_bold = tkFont.Font(weight=tkFont.BOLD, family=ff, size=fs)
    self._line_height = self._font.metrics()["linespace"]

    # Padding and margins
    # NOTE: "bottom": height of panel + border thickness
    self._left, self._right = 2, 2
    self._top, self._bottom = 2, 2
    self._input_height = self._line_height + 4
    self._text_height = self._line_height + 2

    # Create root window
    self._frame = tk.Frame(root)
    self._frame.grid(row=0, column=0)

    # Create gutter input (used as a focus sink; not visible)
    self._gutter = tk.Entry(self._frame, width=10)
    self._gutter.grid(row=0, column=0, sticky=tk.NW)

    # Create primary canvas for displaying the images
    self._canvas = tk.Canvas(self._frame)
    self._canvas.grid(row=0, column=0)

    # Create primary input box
    self._input = tk.Entry(self._frame, font=self._font, width=self._input_width)
    self._input.grid(row=0, column=0, sticky=tk.NW)
    self._input.bind("<Key-Return>", self._input_enter)

    # Configuration after widget construction
    self._input_mode = MODE_NONE
    self._last_input = ""
    self._image = None          # Current image
    self._images = list(images) # Loaded images
    self._photo = None          # Underlying PIL photo object
    self.set_canvas_size(self._compute_size())

    self._actions = collections.defaultdict(list)
    self._functions = {}

  def root(self):
    "Return the root Tk() object"
    return self._root

  def add_mark_function(self, cbfunc, key):
    "Add callback function for when mark key (1..9) is pressed"
    self._functions[key] = cbfunc

  def add_text_function(self, func):
    "Call func(path) and display the result on the image"
    self._text_functions.append(func)

  def actions(self):
    "Return the current actions"
    return self._actions

  def canvas_size(self):
    "Get (canvas_width, canvas_height)"
    return self._canvas["width"], self._canvas["height"]

  def set_canvas_size(self, new_size):
    "Set (canvas_width, canvas_height)"
    w, h = new_size
    self._canvas["width"] = w
    self._canvas["height"] = h

  def _compute_size(self):
    "Return the maximum width and height an image can have"
    return self._width, self._height

  def _path(self):
    "Return the path to the current image"
    return self._images[self._index]

  def _resize_input(self, s):
    "Ensure the input is wide enough to display the string s"
    max_chrs = int(round(self._width / self._font.measure("M")))
    self._input["width"] = min(max(len(s) + 2, INPUT_START_WIDTH), max_chrs)

  def _get_image(self, path):
    "Load (and optionally resize) image specified by path"
    try:
      image = PIL.Image.open(path)
    except IOError as e:
      logger.error("Failed to open image {!r}".format(path))
      logger.exception(e)
      return None
    cw, ch = self._compute_size() 
    iw, ih = image.size
    want_scale = False
    if self._scale_mode == SCALE_EXACT:
      want_scale = True
    elif (iw > cw or ih > ch) and self._scale_mode == SCALE_SHRINK:
      want_scale = True
    if want_scale:
      scale = max(iw/cw, ih/ch)
      nw, nh = int(iw/scale), int(ih/scale)
      logger.debug(f"{path!r}: {iw}x{ih} * {scale} = {nw}x{nh} (fit {cw} {ch})")
      return image.resize((nw, nh))
    return image

  def _draw_text(self, text, xy=(0, 0), anchor=tk.NW,
      fg="white", bg="black", border=1, shiftx=2, shifty=2):
    "Draw text on the canvas with the given parameters"
    x, y = xy
    y += self._input_height
    kws = {"anchor": anchor, "text": text, "font": self._font_bold}
    bg_points = (
      (x-border, y-border),
      (x-border, y+border),
      (x+border, y-border),
      (x+border, y+border)
    )
    for bx, by in bg_points:
      self._canvas.create_text(bx+shiftx, by+shifty, fill=bg, **kws)
    self._canvas.create_text(x+shiftx, y+shifty, fill=fg, **kws)

  def _draw_current(self):
    "Draw self._image to self._canvas"
    w, h = self._compute_size()
    path = self._images[self._index]
    self._photo = PIL.ImageTk.PhotoImage(self._image)
    self._canvas.delete(tk.ALL)
    self._canvas.create_image(w/2, h/2, image=self._photo, anchor=tk.CENTER)
    text_lines = []
    if self._enable_text:
      iw, ih = self._image.size
      st = os.lstat(path)
      ts = fromtimestamp(st.st_mtime).strftime("%Y/%m/%d %H:%M:%S")
      text_lines.extend((
        os.path.basename(path),
        "Size: {}; {}x{}px".format(format_size(st.st_size), iw, ih),
        "Time: {}".format(ts)
      ))
    for func in self._text_functions:
      logger.debug("Text function {!r} for {}".format(func, path))
      text = func(path)
      if type(text) != str:
        text = text.decode("UTF-8")
      text_lines.extend(text.splitlines())
    logger.debug("Drawing lines: {!r}".format(text_lines))
    if len(text_lines) > 0:
      self._draw_text("\n".join(l for l in text_lines))

  def set_index(self, index):
    "Sets the index and displays the image at that index"
    self._index = index
    path = self._images[index]
    count = len(self._images)
    logger.debug("Displaying image {} of {} {!r}".format(index+1, count, path))
    new_title = "{}/{} {}".format(index+1, len(self._images), path)
    self._photo = None
    self._image = self._get_image(path)
    if self._image is None:
      logger.error("Failed to load {!r}!".format(path))
      new_title = "ERROR! " + new_title
      self._canvas.delete(tk.ALL)
    else:
      self._draw_current()
    self.root().title(new_title)

  def redraw_image(self):
    "Recomputes and redraws the current image"
    self.set_index(self._index)

  def _action(self, *args):
    "action(path, action) or action(action): add an action"
    if len(args) == 1:
      path = self._path()
      action = args[0]
    elif len(args) == 2:
      path = args[0]
      action = args[1]
    else:
      raise ValueError("invalid arguments to _action; got {!r}".format(args))
    path = self._path() if len(args) == 1 else args[0]
    action = args[0] if len(args) == 1 else args[1]
    logger.info("{}: {}".format(path, " ".join(action)))
    self._actions[path].append(action)

  def _input_set_text(self, text, select=True):
    "Set the input box's text, optionally selecting the content"
    self._input.delete(0, len(self._input.get()))
    self._input.insert(0, text)
    self._resize_input(text)
    if select:
      self._input.focus()
      self._input.select_range(0, len(text))

  @blocked_by_input
  def _prev_image(self, *args):
    "Navigate to the previous image"
    index = self._index - 1
    if index < 0:
      index = len(self._images) - 1
    self.set_index(index)

  @blocked_by_input
  def _next_image(self, *args):
    "Navigate to the next image"
    index = self._index + 1
    if index >= len(self._images):
      logger.debug("Reached end of image list")
      index = 0
    self.set_index(index)

  @blocked_by_input
  def _rename_image(self, *args):
    "Rename the current image"
    base, name = os.path.split(self._path())
    self._input_mode = MODE_RENAME
    self._input_set_text(name, select=True)

  @blocked_by_input
  def _delete_image(self, *args):
    "Delete the current image"
    self._action(("DELETE",))
    self._next_image()

  @blocked_by_input
  def _go_to_image(self, *args):
    "Navigate to the image with the given number"
    self._input_mode = MODE_SET_IMAGE
    self._input_set_text(self._last_input, select=True)

  @blocked_by_input
  def _find_image(self, *args):
    "Show the first image filename starting with a given prefix"
    self._input_mode = MODE_GOTO
    self._input_set_text(self._last_input, select=True)

  @blocked_by_input
  def _mark_image(self, event):
    "Mark an image for later examination"
    if event.char in self._functions:
      self._functions[event.char](self._path())
    self._action(("MARK-{}".format(event.char),))

  @blocked_by_input
  def _enter_command(self, event):
    "Let the user enter an arbitrary command"
    self._input_mode = MODE_COMMAND
    self._input_set_text("Command?", select=True)

  @blocked_by_input
  def _show_help(self, *args):
    "STUB: Display help text to the user"
    logger.debug("_show_help: {}".format(args))

  @blocked_by_input
  def _adjust(self, event):
    "Fine-tune image size (for testing)"
    if event.char == 'z':
      self._height -= 1
    elif event.char == 'c':
      self._height += 1
    print("Height: {}".format(self._height))
    self.set_index(self._index)

  @blocked_by_input
  def _toggle_zoom(self, event):
    "Advance the zoom method and redraw the image"
    if self._scale_mode == SCALE_NONE:
      self._scale_mode = SCALE_SHRINK
    elif self._scale_mode == SCALE_SHRINK:
      self._scale_mode = SCALE_EXACT
    else:
      self._scale_mode = SCALE_NONE
    notif = "Scaling set to {}".format(self._scale_mode)
    self._input_set_text(notif, select=False)
    self.redraw_image() # Redraw the current image

  def _update_window(self, event):
    "Called when the root window receives a Configure event"
    logger.debug("_update_window on {!r}: {}".format(event.widget, event))
    if event.widget == self._root:
      logger.debug("event: {}".format(dir(event)))
      self._width = event.width - SCREEN_WIDTH_ADJUST
      self._height = event.height# - SCREEN_HEIGHT_ADJUST
      self.redraw_image() # Redraw the current image

  def _do_find_image(self, prefix):
    "Return the path to the next image starting with prefix (or None)"
    for image_path in iterate_from(self._images, self._index):
      base, name = os.path.split(image_path)
      if name.startswith(prefix):
        return image_path

  def _input_enter(self, *args):
    "Called when user presses Enter/Return on the Entry"
    logger.debug("_input_enter: {}".format(args))
    value = self._input.get()
    self._input.delete(0, len(value))
    self._gutter.focus()
    self._last_input = value
    if self._input_mode == MODE_RENAME:
      # Rename the current image to <value>
      base, name = os.path.split(self._path())
      if len(value) > 0 and name != value:
        new_path = os.path.join(base, value)
        logger.info("Rename: {!r} to {!r}".format(self._path(), new_path))
        self._action(("RENAME", new_path))
        self._next_image(*args)
      else:
        logger.info("Invalid new name {!r}".format(value))
    elif self._input_mode == MODE_GOTO:
      # Find and display the next image starting with <value>
      next_image = self._do_find_image(value)
      if next_image is not None:
        self.set_index(self._images.index(next_image))
      else:
        logger.error("Pattern {!r} not found".format(value))
    elif self._input_mode == MODE_SET_IMAGE:
      try:
        idx = (int(value) - 1) % len(self._images)
        logger.info("Navigating to image number {}".format(idx))
        self.set_index(idx)
      except ValueError as e:
        self._input_set_text("Error: {}".format(e))
    elif self._input_mode == MODE_COMMAND:
      logger.info("Executing command {!r}".format(value))
      self._handle_command(value)
    else:
      logger.error("Internal error: invalid mode {}".format(self._input_mode))
    self._input_mode = MODE_NONE

  def _handle_command(self, command):
    "Handle a command entered via the input box"
    cmd_and_args = command.split(None, 1)
    cmd, args = command, ""
    if len(cmd_and_args) == 2:
      cmd, args = cmd_and_args
    logger.info("Handling command {!r} (args {!r})".format(cmd, args))
    if cmd in ("i", "inspect"):
      # Inspect various things
      cw, ch = self.canvas_size()
      logger.info("Root WxH: {}x{}".format(self._width, self._height))
      logger.info("Canvas WxH: {}x{}".format(cw, ch))
      logger.info("Input width={}".format(self._input_width))
      if self._image is not None:
        logger.info("Image size: {}".format(self._image.size))
      else:
        logger.info("No image displayed")
    else:
      self._input_set_text("Invalid command {!r}".format(command), select=False)

  def escape(self, *args):
    "Either cancel rename or exit the application"
    if self._root.focus_get() == self._input:
      self._input_mode = MODE_NONE
      self._input.delete(0, len(self._input.get()))
      self._gutter.focus()
    else:
      self.close(*args)

  def close(self, *args):
    "Exit the application"
    self.root().quit()

def _get_images(*paths, recursive=False):
  "Return a list of all images found in the given paths"
  def list_path(path):
    if os.path.isfile(path):
      yield path
    elif os.path.isdir(path):
      if recursive:
        for r, ds, fs in os.walk(path):
          for f in fs:
            yield os.path.join(r, f)
      else:
        for i in os.listdir(path):
          yield os.path.join(path, i)
    else:
      raise ValueError("Invalid object {!r}".format(path))

  images = []
  for name in paths:
    for filepath in list_path(name):
      mt, me = mimetypes.guess_type(filepath)
      if mt is not None and mt.split("/")[0] == "image":
        images.append(filepath)

  # Filter out the images that can't be loaded
  filtered_images = []
  for idx, image in enumerate(images):
    try:
      PIL.Image.open(image)
      filtered_images.append(image)
    except (IOError, ValueError) as e:
      logger.error("Failed to open image {} {!r}".format(idx, image))
      logger.error("Original exception below:")
      logger.exception(e)
  images = filtered_images

  return images

def main():
  "Entry point"
  ap = argparse.ArgumentParser(add_help=False)
  ap.add_argument("images", nargs="*",
      help="files (or directories) to examine")
  ap.add_argument("-R", "--recurse", action="store_true",
      help="descend into directories recursively to find images")
  ap.add_argument("-F", "--files", metavar="PATH",
      help="read images from %(metavar)s")
  ap.add_argument("--width", type=int,
      help="window width (default: full screen)")
  ap.add_argument("--height", type=int,
      help="window height (default: full screen)")
  ap.add_argument("--add-text", action="store_true",
      help="display image name and attributes over the image")
  ap.add_argument("--add-text-from", metavar="PROG",
      help="display text from program %(metavar)s (see below)")
  ap.add_argument("-o", "--out", metavar="PATH",
      help="write actions to %(metavar)s (default: stdout)")
  ag = ap.add_argument_group("MARK-1 customisation")
  ag.add_argument("--write1", metavar="PATH",
      help="write MARK-1 entries to %(metavar)s")

  ag = ap.add_argument_group("sorting")
  mg = ag.add_mutually_exclusive_group()
  mg.add_argument("-s", "--sort", metavar="KEY", default="name",
      choices=SORT_MODES,
      help="sort images by %(metavar)s: %(choices)s (see below)")
  ag.add_argument("-r", "--reverse", action="store_true",
      help="reverse sorting order")
  mg.add_argument("-T", action="store_true", help="sort by time (--sort=time)")
  mg.add_argument("-S", action="store_true", help="sort by size (--sort=size)")

  ag = ap.add_argument_group("logging")
  ag = ag.add_mutually_exclusive_group()
  ag.add_argument("-v", "--verbose", action="store_true",
      help="verbose output")
  ag.add_argument("-d", "--debug", action="store_true",
      help="alias for --verbose")
  ap.add_argument("-h", "--help", action="store_true",
      help="show this help and exit")
  args = ap.parse_args()
  if args.help:
    ap.print_help()
    sys.stderr.write("""
Note that this program does not actually rename or delete anything. Instead,
the operations are printed to -o,--out (default stdout) for the user to perform
afterwards.
""")
    sys.stderr.write("""
Key actions:
  <Left>      Go to the previous image
  <Right>     Go to the next image
  <Shift-r>   Rename the selected image (<Escape> to cancel)
  <Shift-d>   Delete the selected image
  <Shift-f>   Go to the next image starting with the given text
  <Shift-g>   Go to the image with the given index (starting at 1)
  <Ctrl-w>    Exit the application
  <Escape>    Cancel renaming or exit the application
  <Equal>     Enable or disable downscaling of images to fit the screen
  <1 .. 9>    Mark images for later examination
""")
    sys.stderr.write("""
Sorting actions beginning with "r" simulate passing --reverse. For example,
passing "--sort=rname" is equivalent to "--sort=name --reverse".
""")
    sys.stderr.write("""
Use --text-program to add custom text to each image. The output of the command
`<PROG> "<image-path>"` is added to the text displayed on the image. If <PROG>
starts with a pipe "|", then <image-path> is written to <PROG> and the output
is displayed. Anything <PROG> writes to stderr is displayed directly to the
terminal. Be careful with quoting!
""")
    sys.stderr.write("""
Use --write1 <PATH> to write the current image to <PATH> and immediately flush.
If <PATH> is a file, then it is opened for appending. Otherwise, it is opened
for writing. This is useful for having MARK-1 trigger some other program. For
example, the following line
  --write1 >(while read l; do scp "$l" user@example.com:/home/user; done)
will copy the marked files to /home/user on the server example.com.
""")
    raise SystemExit(0)

  if args.files:
    args.images.extend(open(args.files).read().strip().splitlines())
  elif len(args.images) == 0:
    ap.error("not enough arguments; use --help for info")
  if args.verbose:
    logger.setLevel(logging.DEBUG)

  if args.T:
    args.sort = "time"
  elif args.S:
    args.sort = "size"

  # Get list of paths to images to examine
  images = _get_images(*args.images, recursive=args.recurse)
  if len(images) == 0:
    logger.error("No images left to scan!")
    raise SystemExit(1)

  # Deduce sorting mode and function
  sort_mode = args.sort
  sort_func = lambda fname: fname
  sort_rev = args.reverse
  if args.sort in ("name", "rname"):
    sort_mode = "name"
    sort_func = lambda fname: fname
    sort_rev = (args.sort[0] == "r")
  elif args.sort in ("time", "rtime"):
    sort_mode = "time"
    sort_func = lambda fname: os.stat(fname).st_mtime
    sort_rev = (args.sort[0] == "r")
  elif args.sort in ("size", "rsize"):
    sort_mode = "size"
    sort_func = lambda fname: os.stat(fname).st_size
    sort_rev = (args.sort[0] == "r")

  # Sort the images by the deduced sorting method
  if sort_mode != "none":
    logger.debug("Sorting by {} (reverse={})".format(sort_mode, sort_rev))
    images.sort(key=sort_func)
    if sort_rev:
      images = reversed(images)

  # Construct the application
  skw = {}
  if args.width is not None and args.width > 0:
    skw["width"] = args.width
  if args.height is not None and args.height > 0:
    skw["height"] = args.height
  if args.add_text:
    skw["show_text"] = args.add_text
  if os.path.isfile(Asset("image-x-generic.png")):
    skw["icon"] = Asset("image-x-generic.png")
  s = ImageManager(images, **skw)

  # Add MARK-1 function
  if args.write1:
    mode = "a+t" if os.path.isfile(args.write1) else "wt"
    def mark_func(path):
      "Mark function: write image path to the write1 file"
      with open(args.write1, mode) as fobj:
        fobj.write(path)
        fobj.write("\n")
        fobj.flush()
    s.add_mark_function(mark_func, '1')

  # Add text function
  if args.add_text_from is not None:
    text_program = args.add_text_from
    has_pipe = False
    if text_program.startswith("|"):
      has_pipe = True
      text_program = text_program[1:]
    def make_text_func(prog, pipe=False):
      "Builds the text function; basically just a dummy scope"
      import shlex
      pargs = shlex.split(prog)
      def text_func(path):
        "Return the result of <prog> (with <path> piped in, if desired)"
        spargs = list(pargs)
        spkwargs = {}
        spkwargs["stdout"] = subprocess.PIPE
        spin = None
        if pipe:
          spkwargs["stdin"] = subprocess.PIPE
          spin = path
        else:
          spargs.append(path)
        p = subprocess.Popen(spargs, **spkwargs)
        out, err = p.communicate(input=spin)
        return out
      return text_func
    s.add_text_function(make_text_func(text_program, pipe=has_pipe))

  # Load and display the first image
  s.set_index(0)

  # Don't run the main loop if we're interactive
  if not sys.flags.interactive:
    s.root().mainloop()
    w = csv.writer(sys.stdout)
    for path, actions in s.actions().items():
      for action in actions:
        row = []
        row.append(action[0])
        row.append(path)
        row.extend(action[1:])
        w.writerow(row)

if __name__ == "__main__":
  main()

# vim: set ts=2 sts=2 sw=2 et:
