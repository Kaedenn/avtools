#!/usr/bin/env python3

"""
Display and manage a bunch of images.

This script essentially provides utilities for the following actions:
  Labelling an image
  "Marking" an image (for arbitrary actions, for tracking, etc)
  Moving (renaming) an image file
  Deleting an image

Note that this script does not modify the image files in any way; it neither
renames nor deletes files. Instead, the actions are printed with this script
terminates so that the user can decide how to proceed.

A user can certainly create a mark action to do such a thing, however.
"""

# TODO: README
# TODO: Draw text on its own buffer
# TODO: Implement the arbitrary keybind commands (self._on_keypress)
# TODO: Support webm, webp
# TODO: Support XPM (PIL breaks on images >1bpp)
# TODO: Calculate fullscreen size instead of hard-coding offset adjustments
# TODO: Allow for using different resampling methods for image scaling:
#   PIL.Image.NEAREST   nearest neighbor; simple scaling
#   PIL.Image.BILINEAR  linear interpolation
#   PIL.Image.BICUBIC   cubic interpolation
#   PIL.Image.LANCZOS   high-quality downsampling
# TODO: Allow zoom adjustments (_ and +) to affect other scale modes
# TODO: Remove self._handle_command; move code into self._do_input_command

import argparse
import collections
import csv
import datetime
import functools
import io
import logging
import mimetypes
import os
import random
import shlex
import subprocess
from subprocess import Popen, PIPE
import sys
import textwrap
import tkinter as tk
import tkinter.font as tkfont
from PIL import Image, ImageTk
try:
  import cairosvg
  HAVE_CAIRO_SVG = True
except ImportError:
  sys.stderr.write("cairosvg not found, svg support disabled\n")
  HAVE_CAIRO_SVG = False

LOGGING_FORMAT = "%(filename)s:%(lineno)s:%(levelname)s: %(message)s"

class Logger(logging.Logger):
  TRACE = 5
  def trace(self, message, *args, **kwargs):
    super().log(Logger.TRACE, message, *args, **kwargs, stacklevel=2)

logging.addLevelName(Logger.TRACE, "TRACE")
logging.setLoggerClass(Logger)
logging.basicConfig(format=LOGGING_FORMAT, level=logging.INFO)
logger = logging.getLogger(__name__)

ASSET_PATH = "assets"
FONT = "monospace"
FONT_SIZE = 10

SORT_NONE = "none" # unordered
SORT_RAND = "rand" # randomized
SORT_NAME = "name" # ascending
SORT_TIME = "time" # oldest first
SORT_SIZE = "size" # smallest first
SORT_RNAME = "r" + SORT_NAME # descending
SORT_RTIME = "r" + SORT_TIME # newest first
SORT_RSIZE = "r" + SORT_SIZE # largest first
SORT_MODES = (
  SORT_NONE, SORT_RAND,
  SORT_NAME, SORT_RNAME,
  SORT_TIME, SORT_RTIME,
  SORT_SIZE, SORT_RSIZE)

SCALE_NONE = "none"
SCALE_SHRINK = "shrink"
SCALE_EXACT = "exact"
ZOOM_SCALE_PERCENT = 10   # Amount to scale the image using _ or +

MODE_NONE = "none"
MODE_RENAME = "rename"
MODE_GOTO = "goto"
MODE_SET_IMAGE = "set-image"
MODE_NEXT_SOME = "next-some"
MODE_PREV_SOME = "prev-some"
MODE_LABEL = "label"
MODE_COMMAND = "command"

LINE_FORMAT = "{} {}\n"

INPUT_START_WIDTH = 20
SCREEN_WIDTH_ADJUST = 0
SCREEN_HEIGHT_ADJUST = 100 # TODO: Somehow determine at runtime

PADDING = 2

# Constants affecting text formatting
TF_INCREMENTAL = "incremental"
TF_BOLD = "bold"
TF_BOLD_OFF = "normal"
TF_ITALIC = "italic"
TF_ITALIC_OFF = "roman"
TF_SIZE = "size"
TF_FONT = "family"
TF_COLOR = "color"
TF_FGCOLOR = "fgcolor"
TF_BGCOLOR = "bgcolor"

# Resample methods for scaling images
SAMPLE_METHODS = {
  "N": "NEAREST",
  "BL": "BILINEAR",
  "BC": "BICUBIC",
  "L": "LANCZOS",
  "NEAREST": Image.NEAREST,
  "BILINEAR": Image.BILINEAR,
  "BICUBIC": Image.BICUBIC,
  "LANCZOS": Image.LANCZOS,
}

HELP_KEY_ACTIONS = """
Key actions:
  <Left>      Go to the previous image
  <Right>     Go to the next image
  <Up>        Go to the 10th next image
  <Down>      Go to the 10th previous image
  <Greater>   Advance an arbitrary number of images forward
  <Less>      Advance an arbitrary number of images backward
  <Shift-r>   Mark the current image for rename (<Escape> to cancel)
  <Shift-d>   Mark the current image for deletion
  <Shift-f>   Search for the next image with filename starting with text
  <Shift-g>   Go to the numbered image (starting at 1)
  <Equal>     Toggle downscaling of images to fit the screen
  <1>..<9>    Mark current image for later examination
  <Ctrl-w>    Exit the application
  <Ctrl-q>    Exit the application
  <Escape>    Cancel input or exit the application
  <t>         Toggle displaying text
  <z>, <c>    Adjust canvas size slightly (debugging)
  <l>         "Label" an image, used to take "notes" when viewing images
  <h>         Display this message
  <_>         (<Shift-hyphen>) when zoom mode is none, decrease size by 10%
  <+>         (<Shift-equal>) when zoom mode is none, increase size by 10%
"""

def pipe_program(command, lines):
  """
  Pipe the lines to the command. Returns output as a list of lines.
  """
  inputs = []
  if isinstance(lines, str):
    inputs.append(lines)
  else:
    inputs.extend(lines)
  logger.debug("exec %r with %d inputs", command, len(inputs))

  cmd_args = shlex.split(command)
  proc = Popen(cmd_args, stdin=PIPE, stdout=PIPE, stderr=sys.stderr)
  cmd_input = os.linesep.join(inputs).encode()
  out_data, _ = proc.communicate(input=cmd_input)
  return out_data.decode().splitlines()

def get_asset_path(name):
  """Get the file path to the named asset"""
  self_path = os.path.dirname(os.path.realpath(sys.argv[0]))
  return os.path.join(self_path, ASSET_PATH, name)

def read_images_file(path, relative=False):
  """
  Read a file and return the paths it contains.

  Images are assumed to be relative to the current directory unless
  relative=True, in which case the images are assumed to be relative to
  the file path.
  """
  path_dir = os.path.dirname(path)
  with open(path, "rt") as fobj:
    for line in fobj:
      file_path = line.rstrip()
      if relative and not os.path.isabs(file_path):
        file_path = os.path.join(path_dir, file_path)
      yield file_path

def format_size(nbytes, places=2):
  """Format a number of bytes into '<number> <scale>' string"""
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
  return f"{curr} {bases[base]}"

def format_timestamp(tstamp, formatspec):
  """Format a numeric timestamp"""
  return datetime.datetime.fromtimestamp(tstamp).strftime(formatspec)

def iterate_from(item_list, start_index):
  """Iterate once over thelist, cyclically, starting at the given index"""
  yield from item_list[start_index:]
  yield from item_list[:start_index]

def is_image(filepath):
  """True if the string looks like it refers to an image file"""
  mtype = mimetypes.guess_type(filepath)[0]
  if mtype is not None:
    mcat = mtype.split("/")[0]
    if mcat == "image":
      return True
  return False

def is_svg(filepath):
  """True if the path refers to an SVG file"""
  mtype = mimetypes.guess_type(filepath)[0]
  if mtype is not None:
    mcat, mval = mtype.split("/", 1)
    if mcat == "image" and "svg" in mval:
      return True
  return False

def open_image(filepath):
  """Open the image and return a PIL Image object"""
  try:
    filearg = filepath
    if is_svg(filepath):
      if HAVE_CAIRO_SVG:
        filearg = io.BytesIO(cairosvg.svg2png(url=filepath))
    return Image.open(filearg)
  except IOError as e:
    logger.error("Failed opening image %r: %s", filepath, e)
  return None

def _parse_format_token(token):
  """
  Parse a single keyi or key-value formatting token. Valid tokens are:
    bold, bold=<boolean>      make text bold
    normal, normal=<boolean>  make text normal (un-blold)
    italic, italic=<boolean>  make text italic
    size=<number>             font size in points
    family=<string>           font family
    fgcolor=<color>           text foreground color
    bgcolor=<color>           text background color
  Boolean values have the following behavior:
    True if value is one of "1", "true", or "t"
    False otherwise
  Colors are parsed by Tkinter.
  """
  tkey, tval = None, None
  if token in (TF_BOLD, TF_BOLD_OFF):
    tkey, tval = TF_BOLD, (token == TF_BOLD)
  elif token in (TF_ITALIC, TF_ITALIC_OFF):
    tkey, tval = TF_ITALIC, (token == TF_ITALIC)
  elif token.startswith("x-"):
    tkey, tval = token[2:], None
  elif "=" in token:
    fkey, fval = token.split("=", 1)
    if fkey in (TF_BOLD, TF_ITALIC):
      tkey = fkey
      tval = fval.lower() in ("1", "true", "t")
    elif fkey == TF_SIZE and fval.isdigit():
      tkey, tval = fkey, int(fval)
    elif fkey in TF_FONT:
      tkey, tval = fkey, fval
    elif fkey in (TF_COLOR, TF_FGCOLOR):
      tkey, tval = TF_FGCOLOR, fval
    elif fkey == TF_BGCOLOR:
      tkey, tval = fkey, fval

  if tkey is None:
    logger.warning("Failed to parse token %r", token)

  return tkey, tval

def extract_formatting(text):
  """Extract embedded formatting information, if the text contains any"""
  fields = {}
  remainder = text
  if text.startswith("[[") and "]]" in text:
    spos = text.index("[[")+2 # for possible part-of-line formatting
    epos = text.index("]]")
    tokens = text[spos:epos].replace(", ", ",").split(",")
    remainder = text[epos+2:]
    for token in tokens:
      tkey, tval = _parse_format_token(token)
      if tkey is not None:
        fields[tkey] = tval
  return fields, remainder

def extract_regions(text, start_token, end_token):
  """
  Split text into pieces via start_token and end_token.

  Returns a list of strings. Each string is either raw text or both begins with
  the start token and ends with the end token.

  Nesting regions is not allowed.
  """
  curr_pos = 0
  pieces = []
  start_pos = text.find(start_token, curr_pos)
  while start_pos > -1:
    end_pos = text.find(end_token, start_pos)
    if end_pos > start_pos:
      if start_pos > curr_pos:
        pieces.append(text[curr_pos:start_pos])
      curr_pos = end_pos + len(end_token)
      pieces.append(text[start_pos:curr_pos])
    start_pos = text.find(start_token, curr_pos)
  if -1 < curr_pos < len(text):
    pieces.append(text[curr_pos:])
  return pieces

def parse_formatted_text(text, incremental=False):
  """
  Extract embedded format information, returning a sequence of pairs that can
  be used to draw that text.

  Formatting rules are reset on each new token unless incremental=True.

  Returns a list of pairs (text_rules, text) where:
    text_rules is dict[str, str]
    text is str
  """
  results = []
  rule = {}
  for region in extract_regions(text, "[[", "]]"):
    if region.startswith("[[") and region.endswith("]]"):
      rule_parts = region[2:-2].replace(", ", ",").split(",")
      for part in rule_parts:
        rule_key, rule_val = _parse_format_token(part)
        if rule_key is not None:
          rule[rule_key] = rule_val
      if TF_INCREMENTAL in rule:
        del rule[TF_INCREMENTAL]
        incremental = True
    else:
      results.append((rule, region))
      if not incremental:
        rule = {}
  return results

def _blocked_by_input(func):
  """Restrict a function from being called if self._input has focus"""
  @functools.wraps(func)
  def wrapper(self, *args, **kwargs):
    # pylint: disable=protected-access
    if self.root.focus_get() != self._input:
      return func(self, *args, **kwargs)
    logger.trace("Input has focus; blocking event")
    return None
  return wrapper

class ImageManager:
  # pylint: disable=too-many-instance-attributes
  # pylint: disable=unused-argument, too-many-arguments
  """
  Display images and provide hotkeys to manage them. Does not actually rename
  or delete images.

  Use actions() to obtain the requested actions.

  width: total width of window, borders included
  height: total height of window, borders included
  show_text: if True, display image information in the upper-left corner
  font_family: input and text font (default: monospace)
  font_size: input and text font size (default: 10)
  input_width: width of input box (in characters)
  icon: path to an icon to use for the system tray
  """

  def __init__(self, images,
      width=None,
      height=None,
      show_text=False,
      font_family=FONT,
      font_size=FONT_SIZE,
      input_width=INPUT_START_WIDTH,
      icon=None):
    self._output = []
    self._root = root = tk.Tk()
    root.title("Image Manager") # Default; overwritten shortly with image info
    if icon:
      root.iconphoto(False, ImageTk.PhotoImage(Image.open(icon)))

    # Bind to all relevant top-level events
    root.bind_all("<Key-Escape>", self.escape)
    root.bind_all("<Control-Key-w>", self.close)
    root.bind_all("<Control-Key-q>", self.close)
    root.bind_all("<Key-Left>", self._prev_image)
    root.bind_all("<Key-Right>", self._next_image)
    root.bind_all("<Key-Up>", self._next_many)
    root.bind_all("<Key-Down>", self._prev_many)
    root.bind_all("<Key-greater>", self._next_some)
    root.bind_all("<Key-less>", self._prev_some)
    root.bind_all("<Key-R>", self._rename_image)
    root.bind_all("<Key-D>", self._delete_image)
    root.bind_all("<Key-F>", self._find_image)
    root.bind_all("<Key-G>", self._go_to_image)
    root.bind_all("<Key-colon>", self._go_to_image)
    root.bind_all("<Key-h>", self._show_help)
    root.bind_all("<Key-z>", self._adjust)
    root.bind_all("<Key-c>", self._adjust)
    root.bind_all("<Key-t>", self._toggle_text)
    root.bind_all("<Key-l>", self._label)
    root.bind_all("<Key-slash>", self._enter_command)
    root.bind_all("<Key-equal>", self._toggle_zoom)
    root.bind_all("<Key-plus>", self._zoom_in)
    root.bind_all("<Key-underscore>", self._zoom_out)
    root.bind_all("<Key-space>", self._play_pause)
    root.bind_all("<Key>", self._on_keypress)
    root.bind_all("<ButtonPress-1>", self._on_mouse_press)
    root.bind_all("<B1-Motion>", self._on_mouse_pan)
    root.bind_all("<ButtonRelease-1>", self._on_mouse_release)
    root.bind_all("<ButtonPress-3>", self._on_mouse_right)
    root.bind_all("<MouseWheel>", self._on_mouse_scroll)
    root.bind("<Configure>", self._update_window)
    for i in range(1, 10):
      root.bind_all(f"<Key-{i}>", self._mark_image)

    # Configuration before widget construction: root geometry
    if width is None:
      width = root.winfo_screenwidth() - SCREEN_WIDTH_ADJUST
    if height is None:
      height = root.winfo_screenheight() - SCREEN_HEIGHT_ADJUST
    self._width = width
    self._height = height
    root.geometry(f"{self._width}x{self._height}")

    self._enable_text = show_text
    self._text_functions = []

    # Image size and position
    self._scale_mode = SCALE_SHRINK
    self._scale_amount = 0        # Percentage, >0 to zoom and <0 to shrink
    self._center_offset = [0, 0]  # Tracking delta for image panning
    self._hold_offset = [0, 0]    # Previous offset used during dragging
    self._drag_start = [0, 0]     # Where the dragging started

    # Default font and the font cache
    self._font = tkfont.Font(family=font_family, size=font_size)
    self._font_family = font_family
    self._font_size = font_size
    self._font_cache = {}

    # Create root window
    frame = tk.Frame(root)
    frame.grid(row=0, column=0)
    self._frame = frame

    # Create gutter input (used as a focus sink; not visible)
    self._gutter = tk.Entry(frame)
    self._gutter.grid(row=0, column=0, sticky=tk.NW)

    # Create primary canvas for displaying the images
    self._canvas = tk.Canvas(frame)
    self._canvas.grid(row=0, column=0)
    self._gutter.lower(self._canvas)

    # IDs of temporary objects to remove as soon as the user requests
    self._canvas_temp = []

    # Text drawn on top of the image
    self._text_lines = []
    self._text_ids = []

    # Create primary input box (which starts hidden)
    self._input_mode = MODE_NONE
    self._last_input = ""
    self._input_width = input_width
    self._input_height = self.line_height() + 2*PADDING
    self._input = tk.Entry(frame, font=self._font, width=self._input_width)
    self._input.grid(row=0, column=0, sticky=tk.NW)
    self._input.bind("<Key-Return>", self._input_enter)
    self._input.lower(self._canvas)

    # Image list and current image objects
    self._images = list(images) # Loaded images
    self._count = len(self._images) # Total number of images
    self._index = 0             # Current image index
    self._image = None          # Current PIL.Image object
    self._photo = None          # Tkinter PhotoImage reference
    self._playing = False       # If we are currently playing a GIF
    self._frame_index = 0       # Current frame index when playing a GIF
    self._frame_delay = 100     # Frame delay in milliseconds (10 fps)
    self._sample_method = Image.BICUBIC # rescale resample method

    # Canvas dimensions
    self.set_canvas_size((self._width, self._height))
    self._real_width = 0        # Image's on-disk width
    self._real_height = 0       # Image's on-disk height

    self._keybinds = collections.defaultdict(list)
    self._actions = collections.defaultdict(list)
    self._functions = {}

    self._root.after(self._frame_delay, lambda *_: self._on_frame_tick())

  def char_width(self):
    """Return the width of one 'M' character in the current font"""
    return self._font.measure('M')

  def line_height(self):
    """Return the current font's line height"""
    return self._font.metrics()["linespace"]

  root = property(lambda self: self._root)

  def add_output_file(self, path, lformat=LINE_FORMAT):
    """Write mark actions to the given path"""
    self._output.append({"path": path, "line_format": lformat})

  def add_mark_function(self, cbfunc, key):
    """Add callback function for when mark key (1..9) is pressed"""
    self._functions[key] = cbfunc

  def add_keybind(self, key, command):
    """Bind a key to run a shell command"""
    self._keybinds[key].append(command)

  def add_text_function(self, func):
    """Call func(path) and display the result on the image"""
    self._text_functions.append(func)

  def actions(self):
    """Return the current actions"""
    return self._actions

  def canvas_size(self):
    """Get (canvas_width, canvas_height)"""
    return self._canvas["width"], self._canvas["height"]

  def set_canvas_size(self, new_size):
    """Set (canvas_width, canvas_height)"""
    width, height = new_size
    self._canvas["width"] = width
    self._canvas["height"] = height

  def path(self):
    """Return the path to the current image"""
    # Remove leading "./" if present
    fpath = self._images[self._index]
    leader = f"{os.path.curdir}{os.path.sep}"
    if fpath.startswith(leader):
      fpath = fpath[len(leader):]
    return fpath

  def set_index(self, index, recenter=True, skip_text=None):
    """Sets the index and displays the image at that index"""
    if recenter:
      self._center_offset = [0, 0]

    # Use cached text if we're just redrawing the current image
    if skip_text is None:
      if not self._enable_text:
        skip_text = True
      elif self._text_lines:
        skip_text = (self._index == index)
      else:
        skip_text = False

    self._index = index
    path = self._images[index]

    actions = f"{recenter=} {skip_text=}"
    logger.debug("Image %d/%d %r %s", index+1, self._count, path, actions)

    new_title = f"{index+1}/{self._count} {path}"
    self._image = self._get_image(path)
    if self._image is not None:
      self._draw_current(skip_text=skip_text)
    else:
      logger.error("Failed to load %r!", path)
      new_title = "ERROR! " + new_title
      self._canvas.delete(tk.ALL)

    if self._playing:
      new_title += " (playing)"

    self.root.title(new_title)

  def redraw(self, recenter=True, skip_text=None):
    """Recomputes and redraws the current image"""
    self.set_index(self._index, recenter=recenter, skip_text=skip_text)

  def hide_input(self): # TODO: move text up
    """Hide the input box"""
    self._input.lower(self._canvas)
    #self._input_height = 0
    #self._draw_current()

  def show_input(self): # TODO: move text down
    """Hide the input box"""
    self._input.lift(self._canvas)
    #self._input_height = self.line_height() + 2*PADDING
    #self._draw_current()

  def draw_text(self,
      text,
      pos=(0, 0),       # Where do we put the text?
      anchor=tk.NW,     # How is the text anchored to its position?
      fgcolor="white",  # Foreground (text) color
      bgcolor="black",  # Background (shadow) color
      border=1,         # Shadow size (background offset in pixels)
      shiftx=2,         # Nudge text by this amount horizontally
      shifty=2,         # Nudge text by this amount vertically
      bold=True,        # Make the text bold
      italic=False,     # Make the text italicized
      size=None,        # Use custom size over self._font_size
      family=None):     # Use custom font family over self._font_family
    """
    Draw text on the canvas with the given parameters. Returns the Tkinter IDs
    for the items created. The last ID is always the foreground text.
    """
    # Determine the final font object
    font = self._get_font(bold=bold, italic=italic, size=size, family=family)

    def draw_string(textx, texty, fill):
      """Helper function: actually draw the text"""
      return self._canvas.create_text(textx+shiftx, texty+shifty,
          fill=fill, anchor=anchor, text=text, font=font)

    posx = pos[0]
    posy = pos[1] + self._input_height # Don't cover the input box
    bg_points = (
      (posx-border, posy-border),
      (posx-border, posy+border),
      (posx+border, posy-border),
      (posx+border, posy+border))
    ids = []
    for bgx, bgy in bg_points:
      ids.append(draw_string(bgx, bgy, bgcolor))
    ids.append(draw_string(posx, posy, fgcolor))
    return ids

  # Tkinter callback
  def escape(self, event):
    """Either cancel rename or exit the application"""
    if self._root.focus_get() == self._input:
      self._input_mode = MODE_NONE
      self._input.delete(0, len(self._input.get()))
      self._gutter.focus()
    else:
      self.close(event)

  # Tkinter callback
  def close(self, event):
    """Exit the application"""
    self.root.quit()

  def _resize_input(self, text):
    """Ensure the input is wide enough to display the text"""
    min_chrs = max(len(text), INPUT_START_WIDTH)
    max_chrs = int(round(self._width / self.char_width()))
    self._input["width"] = min(min_chrs, max_chrs)

  def _get_image(self, path):
    """Load (and optionally resize) image specified by path"""
    image = open_image(path)
    if image is None:
      logger.error("Failed to load image")
      return None

    if self._is_animated():
      if 0 <= self._frame_index < image.n_frames:
        image.seek(self._frame_index)

    # Scale the image immediately
    target_w, target_h = self._width, self._height
    image_w, image_h = image.size
    self._real_width = image_w
    self._real_height = image_h
    want_scale = False
    if self._scale_mode == SCALE_EXACT:
      if (image_w, image_h) != (target_w, target_h):
        want_scale = True
    elif self._scale_mode == SCALE_SHRINK:
      if image_w > target_w or image_h > target_h:
        want_scale = True
    elif self._scale_mode == SCALE_NONE and self._scale_amount != 0:
      target_w, target_h = image_w, image_h
      target_w += target_w * self._scale_amount / 100
      target_h += target_h * self._scale_amount / 100
      want_scale = True

    if want_scale:
      scale = max(image_w/target_w, image_h/target_h)
      new_w, new_h = int(image_w/scale), int(image_h/scale)
      logger.debug("Scale %r [%d,%d] by %f to [%d,%d] (to fit %d %d)",
          path, image_w, image_h, scale, new_w, new_h, target_w, target_h)
      image = image.resize((new_w, new_h), self._sample_method)

    return image

  def _get_font(self,
      bold=True,        # Use bold weight over normal
      italic=False,     # Use italic slant over roman
      size=None,        # Use custom size (None -> self._font_size)
      family=None):     # Use custom font face (None -> self._font_family)
    """Obtain a font object and cache it for future use"""
    font = self._font
    if bold or italic or size or family:
      cache_key = (bold, italic, size, family)
      if cache_key not in self._font_cache:
        ffamily = self._font_family if family is None else family
        fsize = self._font_size if size is None else size
        font = tkfont.Font(
            weight=tkfont.BOLD if bold else tkfont.NORMAL,
            slant=tkfont.ITALIC if italic else tkfont.ROMAN,
            family=ffamily,
            size=fsize)
        self._font_cache[cache_key] = font
        logger.debug("Cached font %r as %r", font.actual(), cache_key)
      else:
        font = self._font_cache[cache_key]
    return font

  def _draw_text_lines(self, lines, pos=(0, 0), incremental=False, **kwargs):
    """
    Draw several lines of text.

    Embedded format rules will take precedence over keyword arguments.
    """
    oids = []
    line_space = self._font.metrics("linespace")
    get_rule = lambda table, rule: table.get(rule, kwargs.get(rule))
    for linenr, line in enumerate(lines):
      linex = pos[0]
      for format_rules, text in parse_formatted_text(line, incremental):
        f_bold = get_rule(format_rules, TF_BOLD)
        f_italic = get_rule(format_rules, TF_ITALIC)
        f_size = get_rule(format_rules, TF_SIZE)
        f_family = get_rule(format_rules, TF_FONT)
        font = self._get_font(f_bold, f_italic, f_size, f_family)
        line_space = font.metrics("linespace")
        liney = pos[1] + line_space * linenr
        fkwds = dict(kwargs)
        fkwds.update(format_rules)
        oids.extend(self.draw_text(text, pos=(linex, liney), **fkwds))
        linex += font.measure(text)
    return oids

  def _draw_current(self, skip_text=False):
    """Draw self._image to self._canvas"""
    path = self._images[self._index]
    # NOTE: We store the PhotoImage in a self attribute because create_image()
    # does not properly take ownership of the reference and the PhotoImage
    # object ends up being deallocated almost immediately.
    self._photo = ImageTk.PhotoImage(self._image)
    self._canvas.delete(tk.ALL)
    self._canvas.create_image(
        self._width/2 + self._center_offset[0],
        self._height/2 + self._center_offset[1],
        image=self._photo,
        anchor=tk.CENTER)

    text_lines = list(self._text_lines)
    if not self._enable_text:
      text_lines = []
    elif not skip_text:
      # Add standard text for path, size, and filetime
      text_lines = [os.path.basename(path)]

      realw, realh = self._real_width, self._real_height
      stat = os.stat(path)
      size = format_size(stat.st_size)
      text_lines.append(f"Size: {size}; {realw}x{realh}px")
      imgw, imgh = self._image.size
      if (imgw, imgh) != (realw, realh):
        text_lines.append(f"Resized to {imgw}x{imgh}px")

      tstamp = format_timestamp(stat.st_mtime, "%Y/%m/%d %H:%M:%S")
      text_lines.append(f"Time: {tstamp}")

      # Call the text functions to add whatever they want
      for func in self._text_functions:
        text = func(path)
        # Ensure text is actually a string (and not a bytes type)
        if not isinstance(text, str) and hasattr(text, "decode"):
          text = text.decode()
        text_lines.extend(text.splitlines())

    if text_lines:
      self._text_ids = self._draw_text_lines(text_lines)
    self._text_lines = list(text_lines)

  def _action(self, *args):
    """action(path, action) or action(action): add an action"""
    if len(args) == 1:
      path = self.path()
      action = args[0]
    elif len(args) == 2:
      path = args[0]
      action = args[1]
    else:
      raise ValueError(f"invalid arguments to _action; got {args!r}")
    logger.info("%s: %s", path, " ".join(action))
    self._actions[path].append(action)
    for oentry in self._output:
      fpath = oentry["path"]
      lformat = oentry["line_format"]
      with open(fpath, "at") as fobj:
        fobj.write(lformat.format(path, " ".join(action)))

  def _input_set_text(self, text, select=True):
    """Set the input box's text, optionally selecting the content"""
    self.show_input()
    self._input.delete(0, len(self._input.get()))
    self._input.insert(0, text)
    self._resize_input(text)
    if select:
      self._input.focus()
      self._input.select_range(0, len(text))

  def _do_find_image(self, prefix):
    """Return the path to the next image starting with prefix, if found"""
    for image_path in iterate_from(self._images, self._index + 1):
      name = os.path.basename(image_path)
      if name.startswith(prefix):
        return image_path
    return None

  def _handle_command(self, command):
    """Handle a command entered via the input box"""
    cmd_and_args = command.split(None, 1)
    cmd, args = command, ""
    if len(cmd_and_args) == 2:
      cmd, args = cmd_and_args
    logger.info("Handling command %r (args %r)", cmd, args)
    if cmd in ("delay",):
      try:
        self._frame_delay = int(args)
      except ValueError as err:
        self._input_set_text(f"Error: {err}", select=False)
      logger.info("Configured frame delay to %d (%f fps)",
          self._frame_delay, 1000/self._frame_delay)
    elif cmd in ("fps", "rate"):
      try:
        self._frame_delay = 1000 // int(args)
      except ValueError as err:
        self._input_set_text(f"Error: {err}", select=False)
      logger.info("Configured frame delay to %d (%f fps)",
          self._frame_delay, 1000/self._frame_delay)
    elif cmd in ("i", "inspect"):
      canvw, canvh = self.canvas_size()
      logger.info("Root WxH: %sx%s", self._width, self._height)
      logger.info("Canvas WxH: %sx%s", canvw, canvh)
      logger.info("Input width=%s", self._input_width)
      if self._image is not None:
        logger.info("Image size: %s", self._image.size)
      else:
        logger.info("No image displayed")
    elif cmd in ("sample",):
      alg_name = args
      while SAMPLE_METHODS.get(alg_name) in SAMPLE_METHODS:
        alg_name = SAMPLE_METHODS[alg_name]
      algorithm = SAMPLE_METHODS.get(alg_name)
      if algorithm is None:
        logger.error("Invalid sampling algorithm %r; using NEAREST", alg_name)
        logger.error("Choices: %s", " ".join(SAMPLE_METHODS))
        algorithm = Image.NEAREST
      self._sample_method = algorithm
      self._input_set_text(f"Resample method set to {alg_name}", select=False)
    elif cmd in ("h", "help"):
      self._show_help(None)
      logger.info("Commands:")
      logger.info("delay <MS> - set playback to <MS> milliseconds per frame")
      logger.info("fps|rate <NUM> - set playback to <NUM> frames per second")
      logger.info("i|inspect - inspect the canvas and input sizes")
      logger.info("sample <STR> - set resize sample method to <STR>")
      logger.info("Choices: %s", " ".join(SAMPLE_METHODS))
      logger.info("h|help - display this message and show the help text")
    else:
      self._input_set_text(f"Invalid command {command!r}", select=False)

  def _is_animated(self):
    """True if self._image is an animated image"""
    try:
      return self._image.is_animated
    except AttributeError:
      return False

  # Tkinter callback
  def _on_frame_tick(self):
    """Called to advance a frame in an animated image"""
    if self._playing:
      if self._is_animated():
        self._frame_index += 1
        if self._frame_index >= self._image.n_frames:
          self._frame_index = 0
        self.redraw(skip_text=True)
    self._root.after(self._frame_delay, lambda *_: self._on_frame_tick())

  # Tkinter callback
  def _on_keypress(self, event):
    """Called when any key is pressed"""
    logger.debug("Received keypress %r", event)
    if self._keybinds.get(event.keysym):
      format_keys = dict(
        file=self.path(),
        index=self._index,
        count=self._count,
        dirname=os.path.dirname(self.path()),
        basename=os.path.basename(self.path()),
        cwidth=self._width,
        cheight=self._height,
        iwidth=self._image.size[0],
        iheight=self._image.size[1]
      )
      for command in self._keybinds[event.keysym]:
        cmd = command.format(**format_keys)
        logger.debug("Invoking %r", cmd)
        # TODO: Handle the command, if any
    self._canvas_clear_temp()

  # Tkinter callback
  def _on_mouse_press(self, event):
    """Called when the left mouse button is pressed"""
    logger.trace("Press %s", event)
    self._drag_start = [event.x, event.y]
    self._hold_offset[0] = self._center_offset[0]
    self._hold_offset[1] = self._center_offset[1]

  # Tkinter callback
  def _on_mouse_pan(self, event):
    """Called while we're panning the image"""
    logger.trace("Pan %s", event)
    delta_x = event.x - self._drag_start[0]
    delta_y = event.y - self._drag_start[1]
    final_x = self._hold_offset[0] + delta_x
    final_y = self._hold_offset[1] + delta_y
    if self._center_offset != [final_x, final_y]:
      self._center_offset[0] = final_x
      self._center_offset[1] = final_y
      self._draw_current(skip_text=True)

  # Tkinter callback
  def _on_mouse_release(self, event):
    """Called when the left mouse button is released"""
    logger.trace("Release %s", event)
    self._draw_current(skip_text=False)

  # Tkinter callback
  def _on_mouse_right(self, event):
    """Called when the right mouse button is pressed"""
    if self._center_offset != [0, 0]:
      self._center_offset = [0, 0]
      self._draw_current()

  # Tkinter callback
  def _on_mouse_scroll(self, event):
    """Called when the mouse scroll wheel is used (does not work on Linux)"""
    logger.trace("Scroll %s", event)

  def _canvas_clear_temp(self):
    """Delete temporary items drawn on the canvas"""
    for item in self._canvas_temp:
      self._canvas.delete(item)
    self._canvas_temp = []

  @_blocked_by_input # Tkinter callback and manual call
  def _next_image(self, event):
    """Navigate to the next image"""
    self.set_index((self._index + 1) % self._count)

  @_blocked_by_input # Tkinter callback and manual call
  def _prev_image(self, event):
    """Navigate to the previous image"""
    self.set_index((self._index - 1) % self._count)

  @_blocked_by_input # Tkinter callback
  def _next_many(self, event):
    """Navigate to the 10th next image"""
    self.set_index((self._index + 10) % self._count)

  @_blocked_by_input # Tkinter callback
  def _prev_many(self, event):
    """Navigate to the 10th previous image"""
    self.set_index((self._index - 10) % self._count)

  @_blocked_by_input # Tkinter callback
  def _next_some(self, event):
    """Navigate to the Nth next image"""
    self._input_mode = MODE_NEXT_SOME
    self._input_set_text("N?", select=True)

  @_blocked_by_input # Tkinter callback
  def _prev_some(self, event):
    """Navigate to the Nth next image"""
    self._input_mode = MODE_PREV_SOME
    self._input_set_text("N?", select=True)

  @_blocked_by_input # Tkinter callback
  def _rename_image(self, event):
    """Rename the current image"""
    self._input_mode = MODE_RENAME
    self._input_set_text(os.path.basename(self.path()), select=True)

  @_blocked_by_input # Tkinter callback
  def _delete_image(self, event):
    """Delete the current image"""
    self._action(("DELETE",))
    self._next_image(event)

  @_blocked_by_input # Tkinter callback
  def _go_to_image(self, event):
    """Navigate to the image with the given number"""
    self._input_mode = MODE_SET_IMAGE
    self._input_set_text(self._last_input, select=True)

  @_blocked_by_input # Tkinter callback
  def _find_image(self, event):
    """Show the first image filename starting with a given prefix"""
    self._input_mode = MODE_GOTO
    self._input_set_text(self._last_input, select=True)

  @_blocked_by_input # Tkinter callback
  def _mark_image(self, event):
    """Mark an image for later examination"""
    if event.char in self._functions:
      self._functions[event.char](self.path())
    self._action((f"MARK-{event.char}",))

  @_blocked_by_input # Tkinter callback
  def _label(self, event):
    """Label an image"""
    self._input_mode = MODE_LABEL
    self._input_set_text("Label?", select=True)

  @_blocked_by_input # Tkinter callback
  def _enter_command(self, event):
    """Let the user enter an arbitrary command"""
    self._input_mode = MODE_COMMAND
    self._input_set_text("Command?", select=True)

  @_blocked_by_input # Tkinter callback
  def _show_help(self, event):
    """Display help text to the user"""
    sys.stderr.write(HELP_KEY_ACTIONS)
    help_text = HELP_KEY_ACTIONS
    help_text += "\nPress any key to clear. Text will clear automatically" \
        " after 10 seconds"
    ids = self.draw_text(help_text, (self._width/2, 0), anchor=tk.N)
    self._canvas_temp.extend(ids)
    self._root.after(10000, lambda *_: self._canvas_clear_temp())

  @_blocked_by_input # Tkinter callback
  def _adjust(self, event):
    """Fine-tune image size (for testing)"""
    if event.char == 'z':
      self._height -= 1
    elif event.char == 'c':
      self._height += 1
    print(f"Height after z/c: {self._height}")
    self.redraw(recenter=False)

  @_blocked_by_input # Tkinter callback
  def _toggle_text(self, event):
    """Toggle base text display"""
    self._enable_text = not self._enable_text
    self.redraw(recenter=False)

  @_blocked_by_input # Tkinter callback
  def _toggle_zoom(self, event):
    """Advance the zoom method and redraw the image"""
    if self._scale_mode == SCALE_NONE:
      self._scale_mode = SCALE_SHRINK
    elif self._scale_mode == SCALE_SHRINK:
      self._scale_mode = SCALE_EXACT
    else:
      self._scale_mode = SCALE_NONE
    self._input_set_text(f"Scaling set to {self._scale_mode}", select=False)
    self.redraw(recenter=False)

  @_blocked_by_input # Tkinter callback
  def _zoom_out(self, event):
    """Decrease the scale amount by 10%"""
    self._scale_amount -= ZOOM_SCALE_PERCENT
    self._input_set_text(f"Set scale to {self._scale_amount}%", select=False)
    self.redraw(recenter=False)

  @_blocked_by_input # Tkinter callback
  def _zoom_in(self, event):
    """Increase the scale amount by 10%"""
    self._scale_amount += ZOOM_SCALE_PERCENT
    self._input_set_text(f"Set scale to {self._scale_amount}%", select=False)
    self.redraw(recenter=False)

  @_blocked_by_input # Tkinter callback
  def _play_pause(self, event):
    """Process play/pause event"""
    self._playing = not self._playing
    if self._playing:
      self._frame_index = 0
    elif self._frame_index > 0:
      self._frame_index = 0
      self.set_index(self._index)

  # Tkinter callback
  def _update_window(self, event):
    """Called when the root window receives a Configure event"""
    logger.trace("_update_window on %r: %s", event.widget, event)
    if event.widget == self._root:
      self._width = event.width
      self._height = event.height
      self.redraw(recenter=False)

  def _do_input_rename(self, value):
    """Handle the rename input"""
    base, name = os.path.split(self.path())
    if value and name != value:
      new_path = os.path.join(base, value)
      logger.info("Rename: %r to %r", self.path(), new_path)
      self._action(("RENAME", new_path))
    else:
      logger.info("Invalid new name %r", value)

  def _do_input_goto(self, value):
    """Handle the go-to-image-by-search input"""
    next_image = self._do_find_image(value)
    if next_image is not None:
      self.set_index(self._images.index(next_image))
    else:
      logger.error("Pattern %r not found", value)

  def _do_input_set_image(self, value):
    """Handle the go-to-image-by-number input"""
    try:
      idx = (int(value) - 1) % self._count
      logger.info("Navigating to image number %d", idx)
      self.set_index(idx)
    except ValueError as e:
      logger.error(e)
      self._input_set_text(f"Error: {e}", select=False)

  def _do_input_advance_many(self, value, negative=False):
    """Handle the advance-by-number inputs"""
    try:
      delta = int(value)
      if negative:
        delta = -delta
      index = (self._index + delta) % self._count
      logger.info("Navigating to image number %d", index)
      self.set_index(index)
    except ValueError as e:
      logger.error(e)
      self._input_set_text(f"Error: {e}", select=False)

  def _do_input_label(self, value):
    """Handle the label input"""
    logger.debug("Assigning label %r to %s", value, self.path())
    self._action(("LABEL", value))

  def _do_input_command(self, value):
    """Handle the arbitrary command input"""
    logger.info("Executing command %r", value)
    self._handle_command(value)

  # Tkinter callback
  def _input_enter(self, *args):
    """Called when user presses Enter/Return on the Entry"""
    logger.trace("_input_enter: %s", args)
    value = self._input.get()
    self._input.delete(0, len(value))
    self._gutter.focus()
    self.hide_input()
    self._last_input = value
    if self._input_mode == MODE_RENAME:
      # Rename the current image to <value>
      self._do_input_rename(value)
      self._next_image(*args)
    elif self._input_mode == MODE_GOTO:
      # Find and display the next image starting with <value>
      self._do_input_goto(value)
    elif self._input_mode == MODE_SET_IMAGE:
      # Navigate to the numbered image
      self._do_input_set_image(value)
    elif self._input_mode == MODE_NEXT_SOME:
      # Navigate to the Nth next image
      self._do_input_advance_many(value)
    elif self._input_mode == MODE_PREV_SOME:
      # Navigate to the Nth previous image
      self._do_input_advance_many(value, negative=True)
    elif self._input_mode == MODE_LABEL:
      # Assign a label to the image
      self._do_input_label(value)
    elif self._input_mode == MODE_COMMAND:
      # Execute an arbitrary command
      self._do_input_command(value)
    elif self._input_mode == MODE_NONE:
      logger.warning("Received input %r args %r without mode",
          value, args)
    else:
      logger.error("Internal error: invalid mode %s; value=%r args=%r",
          self._input_mode, value, args)
    self._input_mode = MODE_NONE

def get_images(*paths, recursive=False, quick=False, cont_on_error=False):
  """Return a list of all images found in the given paths"""
  def list_path(path):
    if os.path.isfile(path):
      yield path
    elif os.path.isdir(path):
      if recursive:
        for root, dirs, files in os.walk(path):
          for file in files:
            yield os.path.join(root, file)
      else:
        for item in os.listdir(path):
          yield os.path.join(path, item)
    elif cont_on_error:
      logger.error("Invalid object %r", path)
    else:
      raise ValueError(f"Invalid object {path!r}")

  images = []
  for name in paths:
    for filepath in list_path(name):
      if is_image(filepath):
        images.append(filepath)

  # Filter out the images that can't be loaded
  if not quick:
    filtered_images = []
    for idx, image in enumerate(images):
      try:
        open_image(image)
        filtered_images.append(image)
      except (IOError, ValueError) as e:
        logger.error("Failed to open image %d %r", idx, image)
        logger.error("Original exception below:")
        logger.exception(e)
    images = filtered_images
  else:
    logger.info("Skipping precheck of %d image(s)", len(images))

  return images

def build_mark_write_function(path):
  """Create a mark function to write an image to `path`"""
  mode = "a+t" if os.path.isfile(path) else "wt"
  logger.debug("Building mark function for %r mode %s", path, mode)
  def mark_func(image_path):
    """Mark function: write image path to the path given"""
    with open(path, mode) as fobj:
      fobj.write(image_path)
      fobj.write(os.linesep)
      fobj.close()
  return mark_func

def build_text_function(program_string):
  """Build a text function from a given program string"""
  pipe = False
  prog = program_string
  if prog.startswith("|"):
    pipe = True
    prog = prog[1:]
  def text_func(path):
    """Execute a program and return the output"""
    args = shlex.split(prog)
    p_stdin = None
    p_input = None
    if pipe:
      p_stdin = subprocess.PIPE
      p_input = path.encode()
    else:
      args.append(path)
    cmd = subprocess.list2cmdline(args)
    proc = Popen(args, stdin=p_stdin, stdout=PIPE, stderr=PIPE)
    out, err = proc.communicate(input=p_input)
    if proc.returncode != 0:
      logger.error("Command %r exited nonzero %d", cmd, proc.returncode)
    if err:
      logger.warning("Program %r wrote to stderr:", cmd)
      logger.warning(err.decode().rstrip())
    return out.decode()
  return text_func

def _parse_sort_arg(sort_arg, reverse):
  """Parse a sort argument into a (mode, func, reverse?) triple"""
  sort_mode = sort_arg
  sort_func = lambda fname: fname
  sort_rev = reverse
  if sort_arg.startswith("r") and sort_arg[1:] in SORT_MODES:
    sort_mode = sort_arg[1:]
    sort_rev = True
  if sort_mode == SORT_NAME:
    sort_func = lambda fname: fname
  elif sort_mode == SORT_TIME:
    sort_func = lambda fname: os.stat(fname).st_mtime
  elif sort_mode == SORT_SIZE:
    sort_func = lambda fname: os.stat(fname).st_size
  return sort_mode, sort_func, sort_rev

def _print_help(argparser, args):
  """Print help text"""

  if args.help or args.help_all:
    argparser.print_help()
    sys.stderr.write(textwrap.dedent("""
  Note that this program does not actually rename or delete files. Marks, rename
  commands, and delete commands are written to -o,--out immediately and to the
  controlling terminal after the main loop exits.
  """))
  else:
    argparser.print_usage()

  if args.help_sort or args.help_all:
    sys.stderr.write(textwrap.dedent("""
  Sorting actions beginning with "r" simulate passing --reverse. For example,
  passing "--sort=rname" is equivalent to "--sort=name --reverse".

  The argument to --sort-via must be a program. This program will receive the
  list of files via stdin and must output the files in their final ordering via
  stdout. There are no restrictions on the program's stderr.

  For example, `--sort=name` can be implemented via `--sort-via sort`.
  """))

  if args.help_text_from or args.help_all:
    sys.stderr.write(textwrap.dedent("""
  Use --add-text-from to add custom text to each image. The output of the
  command `<PROG> "<image-path>"` is added to the text displayed on the image.
  If <PROG> starts with a pipe "|", then <image-path> is written to <PROG> and
  the output is displayed. Anything <PROG> writes to stderr is displayed
  directly to the terminal. Be careful with quoting!

  Per-line formatting is supported with simple syntax:
    [[formatting]]text
  where "formatting" is one or more of the following, separated by both a comma
  and a space (", "):
    `bold` or `bold={1,t,true}`     use bold font weight (the default)
    `normal` or `bold={0,f,false}`  use normal font weight
    `italic` or `italic={1,t,true}` make text italic
    `size=NUM`
    `family=STR`
    `color=COLOR` or `fgcolor=COLOR`
    `bgcolor=COLOR`
  For example,
    [[normal, color=red, italic]]This text is red, italic, and not bold
  """))

  if args.help_write or args.help_all:
    sys.stderr.write(textwrap.dedent("""
  Use --write1 <PATH> or --write2 <PATH> to write the current image's file path
  to <PATH> whenever the 1 or 2 key is pressed, respectively. <PATH> is opened
  for appending if it's a normal file and writing otherwise. This is useful for
  having the keypress trigger some other program. For example,
    --write1 >(while read l; do scp "$l" user@example.com:/home/user; done)
  will copy the marked files to the /home/user directory on example.com.

  Use --bind <key> <command> to invoke a command when a key is pressed. <key>
  refers to the keysym (think "key name"). The following escape sequences are
  honored, should the command contain them:
  {file}      path to the image being displayed when the key was pressed
  {index}     image number, starting at 1
  {count}     total number of images
  {dirname}   directory component of the file path
  {basename}  file component of the image path
  """))

  if args.help_keys or args.help_all:
    sys.stderr.write(HELP_KEY_ACTIONS)

def main():
  """Entry point"""
  ap = argparse.ArgumentParser(usage="%(prog)s [arguments] [images ...]",
      add_help=False)
  ag = ap.add_argument_group("image selection")
  ag.add_argument("images", nargs="*",
      help="files (or directories) to examine")
  ag.add_argument("-R", "--recurse", action="store_true",
      help="descend into directories recursively to find images")
  ag.add_argument("-F", "--files", metavar="PATH", action="append",
      help="read images from %(metavar)s")
  ag.add_argument("-L", "--files-relative", action="store_true",
      help="assume images given by -F are relative to the -F argument")
  ag.add_argument("-M", "--max", type=int, metavar="NUM",
      help="after sorting, keep only the first %(metavar)s images")
  ag.add_argument("--skip-precheck", action="store_true",
      help="skip pre-verifying image files (useful for large image sets)")
  ag.add_argument("-E", "--ignore-errors", action="store_true",
      help="continue even if some of the images are invalid")

  ag = ap.add_argument_group("display options")
  ag.add_argument("--width", type=int,
      help="window width (default: full screen)")
  ag.add_argument("--height", type=int,
      help="window height (default: full screen)")
  ag.add_argument("--font-family",
      help="override font (default: {})".format(FONT))
  ag.add_argument("--font-size", type=int,
      help="override font size, in points (default: {})".format(FONT_SIZE))
  ag.add_argument("--add-text", action="store_true",
      help="display image name and attributes over the image")
  ag.add_argument("--add-text-from", action="append", metavar="PROG",
      help="display text from program %(metavar)s (see --help-text-from)")

  ag = ap.add_argument_group("output control")
  ag.add_argument("-o", "--out", metavar="PATH",
      help="write actions to both stdout and %(metavar)s")
  ag.add_argument("-f", "--format", metavar="STR", default=LINE_FORMAT,
      help="output line format (default: %(default)r)")
  ag.add_argument("-a", "--append", action="store_true",
      help="append to the -o,--out file instead of overwriting")
  ag.add_argument("-t", "--text", action="store_true",
      help="output text instead of CSV")

  ag = ap.add_argument_group("keybind actions")
  ag.add_argument("--write1", metavar="PATH",
      help="write current image path to %(metavar)s on MARK-1")
  ag.add_argument("--write2", metavar="PATH",
      help="write current image path to %(metavar)s on MARK-2")
  ag.add_argument("--bind", action="append", metavar="KEY CMD", nargs=2,
      help="bind a keypress to invoke a shell command")

  ag = ap.add_argument_group("sorting")
  mg = ag.add_mutually_exclusive_group()
  mg.add_argument("-s", "--sort", metavar="KEY", default=SORT_NAME,
      choices=SORT_MODES,
      help="sort images by %(metavar)s: %(choices)s (default: %(default)s)")
  mg.add_argument("-S", "--sort-via", metavar="PROG",
      help="sort images by running %(metavar)s")
  ag.add_argument("--seed", help="override random seed for --sort=rand")
  ag.add_argument("-r", "--reverse", action="store_true",
      help="reverse sorting order; sort descending instead of ascending")

  ag = ap.add_argument_group("logging and debugging")
  mg = ag.add_mutually_exclusive_group()
  mg.add_argument("-v", "--verbose", action="store_true",
      help="enable verbose diagnostics")
  mg.add_argument("-V", "--trace", action="store_true",
      help="enable all diagnostics, including the very noisy ones")

  ag = ap.add_argument_group("help text")
  ag.add_argument("-h", "--help", action="store_true",
      help="show this help text")
  ag.add_argument("--help-text-from", action="store_true",
      help="show help text for --add-text-from")
  ag.add_argument("--help-write", action="store_true",
      help="show help text about mark operations")
  ag.add_argument("--help-sort", action="store_true",
      help="show help text about sorting")
  ag.add_argument("--help-keys", action="store_true",
      help="show usage and keypress behaviors")
  ag.add_argument("--help-all", action="store_true",
      help="show all help text")
  args = ap.parse_args()

  if args.trace:
    logger.setLevel(Logger.TRACE)
  elif args.verbose:
    logger.setLevel(logging.DEBUG)

  show_help = any((
    args.help,
    args.help_text_from,
    args.help_write,
    args.help_sort,
    args.help_keys,
    args.help_all))
  if show_help:
    _print_help(ap, args)
    raise SystemExit(0)

  images_args = []
  if args.files:
    for file_path in args.files:
      images_args.extend(read_images_file(file_path,
        relative=args.files_relative))

  if args.images:
    images_args.extend(args.images)

  if not images_args:
    logger.warning("No image paths given; assuming current directory")
    images_args.append(os.curdir)
  logger.debug("Input images: %d: %s", len(images_args), images_args)

  # Get list of paths to images to examine
  images = get_images(*images_args, recursive=args.recurse,
      quick=args.skip_precheck, cont_on_error=args.ignore_errors)
  if not images:
    logger.error("No images left to scan!")
    raise SystemExit(1)

  # Sort the list of files
  if args.sort_via:
    images = pipe_program(args.sort_via, images)
  else:
    # Deduce sorting mode and function
    sort_mode, sort_func, sort_rev = _parse_sort_arg(args.sort, args.reverse)

    # Sort the images by the deduced sorting method
    if sort_mode == SORT_RAND:
      logger.debug("Shuffling images")
      if args.seed:
        rand = random.Random()
        rand.seed(args.seed)
        rand.shuffle(images)
      else:
        random.shuffle(images)
    elif sort_mode != SORT_NONE:
      logger.debug("Sorting by %s (reverse=%s)", sort_mode, sort_rev)
      images.sort(key=sort_func)
      if sort_rev:
        images = list(reversed(images))

  if args.max is not None:
    logger.debug("Keeping only %d of %d images", args.max, len(images))
    images = images[:args.max]

  # Construct the application
  mkwargs = {}
  if args.font_family is not None:
    mkwargs["font_family"] = args.font_family
  if args.font_size is not None:
    mkwargs["font_size"] = args.font_size

  iwidth, iheight = None, None
  if args.width is not None and args.width > 0:
    iwidth = args.width
  if args.height is not None and args.height > 0:
    iheight = args.height

  icon = get_asset_path("image-x-generic.png")
  if not os.path.exists(icon):
    logger.info("Icon %s not found; not using an icon", icon)
    icon = None

  manager = ImageManager(images, width=iwidth, height=iheight,
      show_text=args.add_text, icon=icon, **mkwargs)

  # Register output file, if given
  if args.out is not None:
    if os.path.isfile(args.out) and os.stat(args.out).st_size > 0:
      if not args.append:
        logger.warning("%r: file exists; deleting", args.out)
        os.truncate(args.out, 0)
    manager.add_output_file(args.out, args.format)

  # Register functions to call when a mark key is pressed
  if args.write1:
    manager.add_mark_function(build_mark_write_function(args.write1), '1')
  if args.write2:
    manager.add_mark_function(build_mark_write_function(args.write2), '2')
  if args.bind:
    for bindkey, bindcmd in args.bind:
      manager.add_keybind(bindkey, bindcmd)

  # Register text function(s)
  if args.add_text_from is not None:
    for command in args.add_text_from:
      manager.add_text_function(build_text_function(command))

  # Load and display the first image
  manager.set_index(0)

  # Don't run the main loop if we're interactive
  if not sys.flags.interactive:
    manager.root.mainloop()
    path_actions = list(manager.actions().items())
    if args.text:
      for path, actions in path_actions:
        for action in actions:
          print(" ".join((action[0], path, *action[1:])))
    else:
      writer = csv.writer(sys.stdout)
      for path, actions in path_actions:
        for action in actions:
          row = []
          row.append(action[0])
          row.append(path)
          row.extend(action[1:])
          writer.writerow(row)

if __name__ == "__main__":
  main()

# vim: set ts=2 sts=2 sw=2 et:
