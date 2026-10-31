"""Render installer/app-icon.svg into the app.ico that the app and installer use.

Run it again after changing the SVG:
    .venv/Scripts/python installer/make_icon.py
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "installer" / "app-icon.svg"
TARGET = ROOT / "pdf_compressor" / "gui" / "app.ico"
SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
# By convention only the largest size is stored as PNG; bitmaps keep the
# small sizes readable by every tool that embeds icons.
PNG_FROM = 256


def main() -> int:
    """Write TARGET from SOURCE and return the exit code."""
    app = QGuiApplication([sys.argv[0], "-platform", "offscreen"])
    renderer = QSvgRenderer(str(SOURCE))
    if not renderer.isValid():
        raise SystemExit(f"Could not read {SOURCE}")
    entries = []
    for size in SIZES:
        image = _render(renderer, size)
        entries.append(_png(image) if size >= PNG_FROM else _bitmap(image))
    TARGET.write_bytes(_icon_file(entries))
    app.quit()
    return 0


def _render(renderer: QSvgRenderer, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def _png(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return data.data()


def _bitmap(image: QImage) -> bytes:
    size = image.width()
    stride = image.bytesPerLine()
    pixels = bytes(image.constBits())
    # ARGB32 is stored as B, G, R, A bytes on little-endian Windows, which is
    # the order an icon bitmap wants. Icon bitmaps list rows bottom up.
    rows = [pixels[y * stride : y * stride + size * 4] for y in reversed(range(size))]
    mask_stride = (size + 31) // 32 * 4
    mask = bytearray()
    for row in rows:
        line = bytearray(mask_stride)
        for x in range(size):
            if row[x * 4 + 3] == 0:
                line[x // 8] |= 0x80 >> (x % 8)
        mask += line
    # The height counts the color rows and the transparency mask rows.
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    return header + b"".join(rows) + bytes(mask)


def _icon_file(entries: list[bytes]) -> bytes:
    offset = 6 + 16 * len(entries)
    parts = [struct.pack("<HHH", 0, 1, len(entries))]
    for size, entry in zip(SIZES, entries, strict=True):
        # A size byte of 0 means 256.
        parts.append(
            struct.pack(
                "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(entry), offset
            )
        )
        offset += len(entry)
    return b"".join(parts + entries)


if __name__ == "__main__":
    sys.exit(main())
