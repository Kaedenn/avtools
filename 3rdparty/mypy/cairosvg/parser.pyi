from . import css as css
from .features import match_features as match_features
from .helpers import flatten as flatten, pop_rotation as pop_rotation, rotations as rotations
from .url import fetch as fetch, parse_url as parse_url, read_url as read_url
from _typeshed import Incomplete

NOT_INHERITED_ATTRIBUTES: Incomplete
COLOR_ATTRIBUTES: Incomplete

def handle_white_spaces(string, preserve): ...
def normalize_style_declaration(name, value): ...
def normalize_noop_style_declaration(value): ...
def normalize_url_style_declaration(value): ...
def normalize_font_style_declaration(value): ...

class Node(dict):
    children: Incomplete
    root: bool
    element: Incomplete
    style: Incomplete
    tag: Incomplete
    text: Incomplete
    url_fetcher: Incomplete
    unsafe: Incomplete
    xml_tree: Incomplete
    url: Incomplete
    parent: Incomplete
    def __init__(self, element, style, url_fetcher, parent: Incomplete | None = None, parent_children: bool = False, url: Incomplete | None = None, unsafe: bool = False) -> None: ...
    def fetch_url(self, url, resource_type): ...
    def text_children(self, element, trailing_space, text_root: bool = False): ...
    def get_href(self): ...

class Tree(Node):
    def __new__(cls, **kwargs): ...
    url_fetcher: Incomplete
    url: Incomplete
    xml_tree: Incomplete
    root: bool
    def __init__(self, **kwargs) -> None: ...

CASE_SENSITIVE_STYLE_METHODS: Incomplete
