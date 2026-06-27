#
# The Python Imaging Library.
# $Id$
#
# XPM File handling
#
# History:
# 1996-12-29 fl   Created
# 2001-02-17 fl   Use 're' instead of 'regex' (Python 2.1) (0.7)
# 2026-06-28 ka   Support arbitrary-length pixel character encoding
#                 Support named colors
#
# Copyright (c) Secret Labs AB 1997-2001.
# Copyright (c) Fredrik Lundh 1996-2001.
#
# See the README file for information on usage and redistribution.
#
from __future__ import annotations

import re

from PIL import Image, ImageFile, ImagePalette, ImageColor


def o8(i: int) -> bytes:
    return bytes((i & 255,))


# XPM header
xpm_head = re.compile(b'"([0-9]*) ([0-9]*) ([0-9]*) ([0-9]*)')


def xpm_accept(prefix: bytes) -> bool:
    """Accept XPM files"""
    return prefix[:9] == b"/* XPM */"


class XpmImageFile(ImageFile.ImageFile):
    """
    Image plugin for X11 pixel maps.

    Supports XPM files with more than one bit per pixel and named colors,
    which PIL's built-in XPM plugin does not support.
    """

    format = "XPM"
    format_description = "X11 Pixel Map"

    def _open(self) -> None:
        if not xpm_accept(self.fp.read(9)):
            msg = "not an XPM file; missing magic header"
            raise SyntaxError(msg)

        # skip forward to next string
        while True:
            s = self.fp.readline()
            if not s:
                msg = "broken XPM file; ran out of data before finding header"
                raise SyntaxError(msg)
            m = xpm_head.match(s)
            if m:
                break

        self._size = int(m.group(1)), int(m.group(2))

        pal = int(m.group(3))
        bpp = int(m.group(4))

        if pal > 256:
            msg = "cannot read this XPM file; palette too large"
            raise ValueError(msg)

        if bpp < 1:
            msg = "cannot read this XPM file; bpp must be at least 1"
            raise ValueError(msg)

        self._xpm_bpp = bpp
        self._xpm_palette: dict[bytes, int] = {}

        #
        # load palette description

        palette = [b"\0\0\0"] * 256

        for _ in range(pal):
            s = self.fp.readline()
            if s[-2:] == b"\r\n":
                s = s[:-2]
            elif s[-1:] in b"\r\n":
                s = s[:-1]

            c = s[1 : 1 + bpp]
            index = len(self._xpm_palette)
            self._xpm_palette[c] = index
            s = s[1 + bpp : -2].split()

            for i in range(0, len(s), 2):
                if s[i] == b"c":
                    # process colour key
                    rgb = s[i + 1]
                    if rgb.lower() == b"none":
                        self.info["transparency"] = index
                    else:
                        color = rgb.decode("ascii")

                        try:
                            r, g, b = ImageColor.getrgb(color)[:3]
                        except ValueError as e:
                            msg = f"cannot read XPM color {color!r}"
                            raise ValueError(msg) from e

                        palette[index] = o8(r) + o8(g) + o8(b)
                    break

            else:
                # missing colour key
                msg = "cannot read this XPM file; missing color key"
                raise ValueError(msg)

        self._mode = "P"
        self.palette = ImagePalette.raw("RGB", b"".join(palette))

        self.tile = [("raw", (0, 0) + self.size, self.fp.tell(), ("P", 0, 1))]

    def load_read(self, read_bytes: int) -> bytes:
        """Read the image data"""
        #
        # load all image data in one chunk

        xsize, ysize = self.size

        bpp = self._xpm_bpp
        palette = self._xpm_palette
        rows = []

        for _ in range(ysize):
            s = self.fp.readline()
            if not s:
                msg = "broken XPM file; ran out of data"
                raise SyntaxError(msg)

            # Strip the opening quote and read exactly the encoded pixel data.
            # XPM uses `bpp` characters per pixel, so a row is width * bpp
            # bytes long inside the quoted C string.
            row = s[1 : 1 + xsize * bpp]
            if len(row) < xsize * bpp:
                msg = f"broken XPM file; row {row!r} has length less than {xsize*bpp}"
                raise SyntaxError(msg)

            try:
                rows.append(
                    bytes(palette[row[i : i + bpp]] for i in range(0, xsize * bpp, bpp))
                )
            except KeyError as e:
                msg = f"undefined XPM color key: {e.args[0]!r}"
                raise ValueError(msg) from e

        return b"".join(rows)


#
# Registry handled externally
#

