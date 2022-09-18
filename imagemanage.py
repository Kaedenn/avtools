#!/usr/bin/env python3

"""
Display and manage a bunch of images.

Actions are printed when the program ends; program does not actually delete or
rename anything.
"""

# TODO:
# Display some kind of feedback for when the image is resized
# Support the following image types:
#   XPM
#     PIL.XpmImageFile breaks on images using more than 1 bit per pixel
#   GIF (animated)
#     Requires either multithreading or hooking into the tkinter main loop
#     Note that tkinter is *not* thread-safe!
# Calculate (instead of hard-coding) heights and adjusts (see TODOs below)
#   Calculate the size of the grid cell?
#   Calculate the sizes of the other grid cells?
#   Calculate the positions of the other grid cells and subtract?
# Zenity support where desirable

import argparse
import collections
import csv
import datetime
import functools
import io
import logging
import mimetypes
import os
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
logging.basicConfig(format=LOGGING_FORMAT, level=logging.INFO)
logger = logging.getLogger(__name__)

ASSET_PATH = "assets"
FONT = "monospace"
FONT_SIZE = 10

SORT_NONE = "none" # unordered
SORT_NAME = "name" # ascending
SORT_TIME = "time" # oldest first
SORT_SIZE = "size" # smallest first
SORT_RNAME = "r" + SORT_NAME # descending
SORT_RTIME = "r" + SORT_TIME # newest first
SORT_RSIZE = "r" + SORT_SIZE # largest first
SORT_MODES = (
  SORT_NONE,
  SORT_NAME, SORT_RNAME,
  SORT_TIME, SORT_RTIME,
  SORT_SIZE, SORT_RSIZE)

SCALE_NONE = "none"
SCALE_SHRINK = "shrink"
SCALE_EXACT = "exact"

MODE_NONE = "none"
MODE_RENAME = "rename"
MODE_GOTO = "goto"
MODE_SET_IMAGE = "set-image"
MODE_LABEL = "label"
MODE_COMMAND = "command"

INPUT_START_WIDTH = 20
SCREEN_WIDTH_ADJUST = 0
SCREEN_HEIGHT_ADJUST = 100 # TODO: Somehow determine at runtime

PADDING = 2

HELP_KEY_ACTIONS = """
Key actions:
  <Left>      Go to the previous image
  <Right>     Go to the next image
  <Up>        Go to the 10th next image
  <Down>      Go to the 10th previous image
  <Shift-r>   Mark the current image for rename (<Escape> to cancel)
  <Shift-d>   Mark the current image for deletion
  <Shift-f>   Search for the next image with filename starting with text
  <Shift-g>   Go to the numbered image (starting at 1)
  <Equal>     Toggle downscaling of images to fit the screen
  <1>..<9>    Mark current image for later examination
  <Ctrl-w>    Exit the application
  <Ctrl-q>    Exit the application
  <Escape>    Cancel input or exit the application
  <t>         Toggle displaying standard image text
  <z>, <c>    Adjust canvas size slightly (debugging)
  <l>         "Label" an image, used to take "notes" when viewing images
  <h>         Display this message
"""

def get_asset_path(name):
  """Get the file path to the named asset"""
  self_path = os.path.dirname(os.path.realpath(sys.argv[0]))
  return os.path.join(self_path, ASSET_PATH, name)

def format_size(nbytes, places=2):
  """Format a number of bytes"""
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
  """Iterate over an entire list, cyclically, starting at the given index + 1"""
  curr = start_index + 1
  while curr < len(item_list):
    yield item_list[curr]
    curr += 1
  curr = 0
  while curr < start_index:
    yield item_list[curr]
    curr += 1
  yield item_list[start_index]

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

def blocked_by_input(func):
  """Block a function from being called if self._input has focus"""
  @functools.wraps(func)
  def wrapper(self, *args, **kwargs):
    # pylint: disable=protected-access
    if self.root.focus_get() != self._input:
      return func(self, *args, **kwargs)
    logger.debug("Input has focus; blocking event")
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
    root.title("Image Manager") # Default; overwritten shortly
    if icon:
      icon_image = Image.open(icon)
      root.iconphoto(False, ImageTk.PhotoImage(icon_image))

    # Bind to all relevant top-level events
    root.bind_all("<Key-Escape>", self.escape)
    root.bind_all("<Control-Key-w>", self.close)
    root.bind_all("<Control-Key-q>", self.close)
    root.bind_all("<Key-Left>", self._prev_image)
    root.bind_all("<Key-Right>", self._next_image)
    root.bind_all("<Key-Up>", self._next_many)
    root.bind_all("<Key-Down>", self._prev_many)
    root.bind_all("<Key-R>", self._rename_image)
    root.bind_all("<Key-D>", self._delete_image)
    root.bind_all("<Key-F>", self._find_image)
    root.bind_all("<Key-G>", self._go_to_image)
    root.bind_all("<Key-h>", self._show_help)
    root.bind_all("<Key-z>", self._adjust)
    root.bind_all("<Key-c>", self._adjust)
    root.bind_all("<Key-t>", self._toggle_text)
    root.bind_all("<Key-l>", self._label)
    root.bind_all("<Key-equal>", self._toggle_zoom)
    root.bind_all("<Key-slash>", self._enter_command)
    root.bind_all("<Key>", self._on_keypress)
    root.bind("<Configure>", self._update_window)
    for i in range(1, 10):
      root.bind_all(f"<Key-{i}>", self._mark_image)

    # Configuration before widget construction
    if width is None:
      width = root.winfo_screenwidth() - SCREEN_WIDTH_ADJUST
    if height is None:
      height = root.winfo_screenheight() - SCREEN_HEIGHT_ADJUST
    self._width = width
    self._height = height
    root.geometry(f"{self._width}x{self._height}")

    self._enable_text = show_text
    self._text_functions = []
    self._scale_mode = SCALE_SHRINK

    self._font_family = font_family
    self._font_size = font_size

    # Normal font object
    self._font = tkfont.Font(
        family=self._font_family,
        size=self._font_size)
    # Bold font object
    self._font_bold = tkfont.Font(
        weight=tkfont.BOLD,
        family=self._font_family,
        size=self._font_size)

    self._input_width = input_width
    self._input_height = self.line_height() + 2*PADDING

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

    # IDs of temporary objects to remove as soon as the user requests
    self._canvas_temp = []

    # Create primary input box
    self._input = tk.Entry(frame, font=self._font, width=self._input_width)
    self._input.grid(row=0, column=0, sticky=tk.NW)
    self._input.bind("<Key-Return>", self._input_enter)

    # Configuration after widget construction
    self._input_mode = MODE_NONE
    self._last_input = ""
    self._images = list(images) # Loaded images
    self._count = len(self._images) # Total number of images
    self._image = None          # Current image
    self._index = 0             # Current image index
    self._photo = None          # Underlying PIL photo object
    self.set_canvas_size((self._width, self._height))

    self._keybinds = collections.defaultdict(list)
    self._actions = collections.defaultdict(list)
    self._functions = {}

  def add_output_file(self, path, lformat="{!r} {!r}\n"):
    """Write mark actions to the given path"""
    self._output.append({
      "path": path,
      "line_format": lformat
    })

  def char_width(self):
    """Return the width of one 'M' character in the current font"""
    return self._font.measure('M')

  def line_height(self):
    """Return the current font's line height"""
    return self._font.metrics()["linespace"]

  @property
  def root(self):
    """Return the root Tk() object"""
    return self._root

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
    return self._images[self._index]

  def _resize_input(self, s):
    """Ensure the input is wide enough to display the string s"""
    min_chrs = max(len(s), INPUT_START_WIDTH)
    max_chrs = int(round(self._width / self.char_width()))
    self._input["width"] = min(min_chrs, max_chrs)

  def _get_image(self, path):
    """Load (and optionally resize) image specified by path"""
    image = open_image(path)
    if image is None:
      logger.error("Failed to load image")
      return None
    # Determine if we should resize the image
    cnvw, cnvh = self._width, self._height
    imgw, imgh = image.size
    want_scale = False
    if self._scale_mode == SCALE_EXACT and (imgw != cnvw or imgh != cnvh):
      want_scale = True
    elif self._scale_mode == SCALE_SHRINK and (imgw > cnvw or imgh > cnvh):
      want_scale = True
    if want_scale:
      scale = max(imgw/cnvw, imgh/cnvh)
      neww, newh = int(imgw/scale), int(imgh/scale)
      logger.debug("Scale %r [%d,%d] by %f to [%d,%d] (to fit %d %d)",
          path, imgw, imgh, scale, neww, newh, cnvw, cnvh)
      return image.resize((neww, newh))
    return image

  def _draw_text(self,
      text,
      pos=(0, 0),       # Where do we put the text?
      anchor=tk.NW,     # How is the text anchored to its position?
      fgcolor="white",  # Foreground (text) color
      bgcolor="black",  # Background (shadow) color
      border=1,         # Shadow size (distance between fg and bg)
      shiftx=2,         # Nudge text by this amount horizontally
      shifty=2,         # Nudge text by this amount vertically
      bold=True):
    """
    Draw text on the canvas with the given parameters. Returns the Tkinter IDs
    for the items created. The last ID is always the foreground text.
    """
    def draw_string(textx, texty, fill):
      """Helper function: actually draw the text"""
      return self._canvas.create_text(textx+shiftx, texty+shifty,
          fill=fill,
          anchor=anchor,
          text=text,
          font=self._font_bold if bold else self._font)
    posx, posy = pos
    # FIXME: Calling code should compensate for the input box size
    posy += self._input_height # Don't cover the input box
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

  def _draw_current(self):
    """Draw self._image to self._canvas"""
    path = self._images[self._index]
    # NOTE: We store the PhotoImage in a self attribute because create_image()
    # does not properly take ownership of the reference and the PhotoImage
    # object ends up being deallocated almost immediately.
    self._photo = ImageTk.PhotoImage(self._image)
    # Clear the canvas
    self._canvas.delete(tk.ALL)
    # Display the image, centered
    self._canvas.create_image(
        self._width/2,
        self._height/2,
        image=self._photo,
        anchor=tk.CENTER)

    text_lines = []
    if self._enable_text:
      # Add standard text for path, size, and filetime
      imgw, imgh = self._image.size
      stat = os.lstat(path)
      tstamp = format_timestamp(stat.st_mtime, "%Y/%m/%d %H:%M:%S")
      size = format_size(stat.st_size)
      text_lines.extend((
        os.path.basename(path),
        f"Size: {size}; {imgw}x{imgh}px",
        f"Time: {tstamp}"))

    # Call the text functions to add whatever they want
    for func in self._text_functions:
      logger.debug("Text function %r for %s", func, path)
      text = func(path)
      # Ensure text is actually a string (and not a bytes type)
      if not isinstance(text, str) and hasattr(text, "decode"):
        text = text.decode()
      text_lines.extend(text.splitlines())

    if text_lines:
      logger.debug("Drawing %d lines of text: %r", len(text_lines), text_lines)
      self._draw_text("\n".join(l for l in text_lines))

  def set_index(self, index):
    """Sets the index and displays the image at that index"""
    self._index = index
    path = self._images[index]
    logger.debug("Displaying image %s of %s %r", index+1, self._count, path)
    new_title = f"{index+1}/{self._count} {path}"
    self._image = self._get_image(path)
    if self._image is None:
      logger.error("Failed to load %r!", path)
      new_title = "ERROR! " + new_title
      self._canvas.delete(tk.ALL)
    else:
      self._draw_current()
    self.root.title(new_title)

  def redraw(self):
    """Recomputes and redraws the current image"""
    self.set_index(self._index)

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
    self._input.delete(0, len(self._input.get()))
    self._input.insert(0, text)
    self._resize_input(text)
    if select:
      self._input.focus()
      self._input.select_range(0, len(text))

  def _do_find_image(self, prefix):
    """Return the path to the next image starting with prefix, if found"""
    for image_path in iterate_from(self._images, self._index):
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
    if cmd in ("i", "inspect"):
      # Inspect various things
      canvw, canvh = self.canvas_size()
      logger.info("Root WxH: %sx%s", self._width, self._height)
      logger.info("Canvas WxH: %sx%s", canvw, canvh)
      logger.info("Input width=%s", self._input_width)
      if self._image is not None:
        logger.info("Image size: %s", self._image.size)
      else:
        logger.info("No image displayed")
    elif cmd in ("h", "help"):
      self._show_help(None)
    else:
      self._input_set_text("Invalid command {command!r}", select=False)

  def _on_keypress(self, event):
    """Called when any key is pressed"""
    logger.debug("received keypress %r", event)
    if event.keysym in self._keybinds and self._keybinds[event.keysym]:
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
    self._canvas_clear_temp()

  def _canvas_clear_temp(self):
    """Delete temporary items drawn on the canvas"""
    for item in self._canvas_temp:
      self._canvas.delete(item)
    self._canvas_temp = []

  @blocked_by_input # Tkinter callback and manual call
  def _prev_image(self, event):
    """Navigate to the previous image"""
    index = self._index - 1
    if index < 0:
      index = self._count - 1
    self.set_index(index)

  @blocked_by_input # Tkinter callback and manual call
  def _next_image(self, event):
    """Navigate to the next image"""
    index = self._index + 1
    if index >= self._count:
      logger.debug("Reached end of image list")
      index = 0
    self.set_index(index)

  @blocked_by_input # Tkinter callback
  def _next_many(self, event):
    """Navigate to the 10th next image"""
    self.set_index((self._index + 10) % self._count)

  @blocked_by_input # Tkinter callback
  def _prev_many(self, event):
    """Navigate to the 10th previous image"""
    self.set_index((self._index - 10) % self._count)

  @blocked_by_input # Tkinter callback
  def _rename_image(self, event):
    """Rename the current image"""
    self._input_mode = MODE_RENAME
    self._input_set_text(os.path.basename(self.path()), select=True)

  @blocked_by_input # Tkinter callback
  def _delete_image(self, event):
    """Delete the current image"""
    self._action(("DELETE",))
    self._next_image(event)

  @blocked_by_input # Tkinter callback
  def _go_to_image(self, event):
    """Navigate to the image with the given number"""
    self._input_mode = MODE_SET_IMAGE
    self._input_set_text(self._last_input, select=True)

  @blocked_by_input # Tkinter callback
  def _find_image(self, event):
    """Show the first image filename starting with a given prefix"""
    self._input_mode = MODE_GOTO
    self._input_set_text(self._last_input, select=True)

  @blocked_by_input # Tkinter callback
  def _mark_image(self, event):
    """Mark an image for later examination"""
    if event.char in self._functions:
      self._functions[event.char](self.path())
    self._action((f"MARK-{event.char}",))

  @blocked_by_input # Tkinter callback
  def _label(self, event):
    """Label an image"""
    self._input_mode = MODE_LABEL
    self._input_set_text("Label?", select=True)

  @blocked_by_input # Tkinter callback
  def _enter_command(self, event):
    """Let the user enter an arbitrary command"""
    self._input_mode = MODE_COMMAND
    self._input_set_text("Command?", select=True)

  @blocked_by_input # Tkinter callback
  def _show_help(self, event):
    """Display help text to the user"""
    sys.stderr.write(HELP_KEY_ACTIONS)
    help_text = HELP_KEY_ACTIONS
    help_text += "\nPress any key to clear. Text will clear automatically" \
        " after 10 seconds"
    ids = self._draw_text(help_text, (self._width/2, 0), anchor=tk.N)
    self._canvas_temp.extend(ids)
    self._root.after(10000, lambda *_: self._canvas_clear_temp())

  @blocked_by_input # Tkinter callback
  def _adjust(self, event):
    """Fine-tune image size (for testing)"""
    if event.char == 'z':
      self._height -= 1
    elif event.char == 'c':
      self._height += 1
    print(f"Height: {self._height}")
    self.redraw()

  @blocked_by_input # Tkinter callback
  def _toggle_text(self, event):
    """Toggle base text display"""
    self._enable_text = not self._enable_text
    self.redraw()

  @blocked_by_input # Tkinter callback
  def _toggle_zoom(self, event):
    """Advance the zoom method and redraw the image"""
    if self._scale_mode == SCALE_NONE:
      self._scale_mode = SCALE_SHRINK
    elif self._scale_mode == SCALE_SHRINK:
      self._scale_mode = SCALE_EXACT
    else:
      self._scale_mode = SCALE_NONE
    notif = f"Scaling set to {self._scale_mode}"
    self._input_set_text(notif, select=False)
    self.redraw()

  # Tkinter callback
  def _update_window(self, event):
    """Called when the root window receives a Configure event"""
    logger.debug("_update_window on %r: %s", event.widget, event)
    if event.widget == self._root:
      self._width = event.width
      self._height = event.height
      self.redraw()

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
      self._input_set_text(f"Error: {e}")

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
    logger.debug("_input_enter: %s", args)
    value = self._input.get()
    self._input.delete(0, len(value))
    self._gutter.focus()
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
    elif self._input_mode == MODE_LABEL:
      # Assign a label to the image
      self._do_input_label(value)
    elif self._input_mode == MODE_COMMAND:
      # Execute an arbitrary command
      self._do_input_command(value)
    else:
      logger.error("Internal error: invalid mode %s", self._input_mode)
    self._input_mode = MODE_NONE

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

def get_images(*paths, recursive=False, quick=False):
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
  """))

  if args.help_text_from or args.help_all:
    sys.stderr.write(textwrap.dedent("""
  Use --add-text-from to add custom text to each image. The output of the
  command `<PROG> "<image-path>"` is added to the text displayed on the image.
  If <PROG> starts with a pipe "|", then <image-path> is written to <PROG> and
  the output is displayed. Anything <PROG> writes to stderr is displayed
  directly to the terminal. Be careful with quoting!
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
  ag.add_argument("-F", "--files", metavar="PATH",
      help="read images from %(metavar)s")
  ag.add_argument("--skip-precheck", action="store_true",
      help="skip preloading images (useful for large image sets)")

  ag = ap.add_argument_group("display options")
  ag.add_argument("--width", type=int,
      help="window width (default: full screen)")
  ag.add_argument("--height", type=int,
      help="window height (default: full screen)")
  ag.add_argument("--font-family",
      help="override font (default: monospace)")
  ag.add_argument("--font-size", type=int,
      help="override font size, in points")
  ag.add_argument("--add-text", action="store_true",
      help="display image name and attributes over the image")
  ag.add_argument("--add-text-from", metavar="PROG",
      help="display text from program %(metavar)s (see --help-text-from)")
  ag.add_argument("--help-text-from", action="store_true",
      help="show help text for --add-text-from")

  ag = ap.add_argument_group("output control")
  ag.add_argument("-o", "--out", metavar="PATH",
      help="write actions to both stdout and %(metavar)s")
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
  ag.add_argument("--help-write", action="store_true",
      help="show help text about mark operations")

  ag = ap.add_argument_group("sorting")
  mg = ag.add_mutually_exclusive_group()
  mg.add_argument("-s", "--sort", metavar="KEY", default=SORT_NAME,
      choices=SORT_MODES,
      help="sort images by %(metavar)s: %(choices)s (default: %(default)s)")
  ag.add_argument("-r", "--reverse", action="store_true",
      help="reverse sorting order; sort descending instead of ascending")
  mg.add_argument("-T", action="store_true", help="sort by time (--sort=time)")
  mg.add_argument("-S", action="store_true", help="sort by size (--sort=size)")
  mg.add_argument("--help-sort", action="store_true",
      help="show help text about sorting")

  ag = ap.add_argument_group("logging")
  mg = ag.add_mutually_exclusive_group()
  mg.add_argument("-v", "--verbose", action="store_true",
      help="verbose output")
  mg.add_argument("-d", "--debug", action="store_true",
      help="alias for --verbose")

  ag = ap.add_argument_group("other help text")
  ag.add_argument("-h", "--help", action="store_true",
      help="show this help text")
  ag.add_argument("--help-keys", action="store_true",
      help="show usage and keypress behaviors")
  ag.add_argument("--help-all", action="store_true",
      help="show all help text")
  args = ap.parse_args()

  if args.verbose:
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
    with open(args.files, "rt") as fobj:
      for line in fobj:
        images_args.append(line.rstrip())

  if args.images:
    images_args.extend(args.images)

  if not images_args:
    ap.error("not enough arguments; use --help for info")

  if args.T:
    args.sort = SORT_TIME
  elif args.S:
    args.sort = SORT_SIZE

  # Get list of paths to images to examine
  images = get_images(*images_args, recursive=args.recurse,
      quick=args.skip_precheck)
  if not images:
    logger.error("No images left to scan!")
    raise SystemExit(1)

  # Deduce sorting mode and function
  sort_mode, sort_func, sort_rev = _parse_sort_arg(args.sort, args.reverse)

  # Sort the images by the deduced sorting method
  if sort_mode != SORT_NONE:
    logger.debug("Sorting by %s (reverse=%s)", sort_mode, sort_rev)
    images.sort(key=sort_func)
    if sort_rev:
      images = list(reversed(images))

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
    icon = None

  manager = ImageManager(images, width=iwidth, height=iheight,
      show_text=args.add_text,
      icon=icon,
      **mkwargs)

  # Register output file, if given
  if args.out is not None:
    if os.path.isfile(args.out) and os.stat(args.out).st_size > 0:
      if not args.append:
        logger.warning("%r: file exists; deleting", args.out)
        os.truncate(args.out, 0)
    manager.add_output_file(args.out)

  # Register functions to call when a mark key is pressed
  if args.write1:
    manager.add_mark_function(build_mark_write_function(args.write1), '1')
  if args.write2:
    manager.add_mark_function(build_mark_write_function(args.write2), '2')
  if args.bind:
    for bindkey, bindcmd in args.bind:
      manager.add_keybind(bindkey, bindcmd)

  # Register text function
  if args.add_text_from is not None:
    manager.add_text_function(build_text_function(args.add_text_from))

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
