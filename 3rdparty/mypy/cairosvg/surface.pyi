from .colors import color as color, negate_color as negate_color
from .defs import apply_filter_after_painting as apply_filter_after_painting, apply_filter_before_painting as apply_filter_before_painting, clip_path as clip_path, filter_ as filter_, gradient_or_pattern as gradient_or_pattern, linear_gradient as linear_gradient, marker as marker, mask as mask, paint_mask as paint_mask, parse_all_defs as parse_all_defs, pattern as pattern, prepare_filter as prepare_filter, radial_gradient as radial_gradient, use as use
from .helpers import PointError as PointError, UNITS as UNITS, clip_rect as clip_rect, node_format as node_format, normalize as normalize, paint as paint, preserve_ratio as preserve_ratio, size as size, transform as transform
from .image import image as image, invert_image as invert_image
from .parser import Tree as Tree
from .path import draw_markers as draw_markers, path as path
from .shapes import circle as circle, ellipse as ellipse, line as line, polygon as polygon, polyline as polyline, rect as rect
from .svg import svg as svg
from .text import text as text
from .url import parse_url as parse_url
from _typeshed import Incomplete

SHAPE_ANTIALIAS: Incomplete
TEXT_ANTIALIAS: Incomplete
TEXT_HINT_STYLE: Incomplete
TEXT_HINT_METRICS: Incomplete
TAGS: Incomplete
PATH_TAGS: Incomplete
INVISIBLE_TAGS: Incomplete

class Surface:
    surface_class: Incomplete
    @classmethod
    def convert(cls, bytestring: Incomplete | None = None, *, file_obj: Incomplete | None = None, url: Incomplete | None = None, dpi: int = 96, parent_width: Incomplete | None = None, parent_height: Incomplete | None = None, scale: int = 1, unsafe: bool = False, background_color: Incomplete | None = None, negate_colors: bool = False, invert_images: bool = False, write_to: Incomplete | None = None, output_width: Incomplete | None = None, output_height: Incomplete | None = None, **kwargs): ...
    cairo: Incomplete
    cursor_position: Incomplete
    cursor_d_position: Incomplete
    text_path_width: int
    tree_cache: Incomplete
    markers: Incomplete
    gradients: Incomplete
    patterns: Incomplete
    masks: Incomplete
    paths: Incomplete
    filters: Incomplete
    images: Incomplete
    output: Incomplete
    dpi: Incomplete
    font_size: Incomplete
    stroke_and_fill: bool
    context: Incomplete
    map_rgba: Incomplete
    map_image: Incomplete
    def __init__(self, tree, output, dpi, parent_surface: Incomplete | None = None, parent_width: Incomplete | None = None, parent_height: Incomplete | None = None, scale: int = 1, output_width: Incomplete | None = None, output_height: Incomplete | None = None, background_color: Incomplete | None = None, map_rgba: Incomplete | None = None, map_image: Incomplete | None = None) -> None: ...
    @property
    def points_per_pixel(self): ...
    @property
    def device_units_per_user_units(self): ...
    context_width: Incomplete
    context_height: Incomplete
    def set_context_size(self, width, height, viewbox, tree) -> None: ...
    def finish(self) -> None: ...
    def map_color(self, string, opacity: int = 1): ...
    parent_node: Incomplete
    def draw(self, node) -> None: ...

class PDFSurface(Surface):
    surface_class: Incomplete

class PSSurface(Surface):
    surface_class: Incomplete

class EPSSurface(Surface): ...

class PNGSurface(Surface):
    device_units_per_user_units: int
    def finish(self): ...

class SVGSurface(Surface):
    surface_class: Incomplete

def parse_font(value): ...
