"""Compress one PDF into a verified temp file."""

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType

import pymupdf
from pymupdf import mupdf

from pdf_compressor.core.settings import Level

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LevelParams:
    """Resample images above dpi_threshold to dpi_target as JPEG at quality."""

    dpi_threshold: int
    dpi_target: int
    quality: int


LEVELS: Mapping[Level, LevelParams] = MappingProxyType(
    {
        Level.LOW: LevelParams(dpi_threshold=250, dpi_target=200, quality=85),
        Level.MEDIUM: LevelParams(dpi_threshold=200, dpi_target=150, quality=75),
        Level.HIGH: LevelParams(dpi_threshold=150, dpi_target=100, quality=60),
    }
)
MIN_SAVING = 0.10
MB = 1_000_000
# None of these is an OSError, and a failed save raises only FzErrorBase.
PYMUPDF_ERRORS = (RuntimeError, ValueError, mupdf.FzErrorBase)

COMPRESSED = "Compressed"
ALREADY_SMALL = "Already small"
SKIP_SECURED = "Skipped: password-protected or secured"
SKIP_SIGNED = "Skipped: digitally signed"
SKIP_DAMAGED = "Skipped: can't be opened (it may be damaged)"
SKIP_IN_USE = "Skipped: open in another program"
SKIP_MISSING = "Skipped: file not found"
OVER_LIMIT = (
    "Still {size}. That's over your {limit:g} MB limit, so it may need splitting."
)

_IMAGE_KINDS = ("color_lossless", "color_lossy", "gray_lossless", "gray_lossy")
_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
_DEVICE_SPACE_FOR_COUNT = MappingProxyType(
    {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}
)
_COUNT_FOR_DEVICE_SPACE = MappingProxyType(
    {"/DeviceGray": 1, "/DeviceRGB": 3, "/DeviceCMYK": 4}
)
_COUNT_FOR_FAMILY = MappingProxyType({"CalGray": 1, "CalRGB": 3, "Lab": 3})


class DamagedError(Exception):
    """MuPDF had to repair the file while compressing it, so it is damaged."""


class Status(Enum):
    """What happened to one file."""

    COMPRESSED = "compressed"
    ALREADY_SMALL = "already small"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class FileResult:
    """The outcome for one file, as the results table shows it."""

    source: Path
    before: int
    after: int | None
    status: Status
    message: str
    over_limit: bool = False


def compress_file(
    source: Path,
    tmp: Path,
    level: Level,
    remove_hidden_info: bool,
    size_limit_mb: float | None,
) -> FileResult:
    """Compress source into tmp, keeping tmp only when every check passes."""
    # Warnings from earlier work belong to that work, not to this file.
    _drain_warnings(None)
    try:
        return _compress(source, tmp, level, remove_hidden_info, size_limit_mb)
    finally:
        _drain_warnings(source)


def format_mb(size: int) -> str:
    """Show a size in decimal megabytes: one decimal from 1 MB up, two below."""
    value = size / MB
    digits = f"{value:.1f}" if value >= 1 else f"{value:.2f}"
    return f"{digits.rstrip('0').rstrip('.')} MB"


def over_limit_message(size: int, limit_mb: float) -> str:
    """Return the Status text for a file that is still over the size limit."""
    return OVER_LIMIT.format(size=format_mb(size), limit=limit_mb)


def saves_enough(before: int, after: int) -> bool:
    """Return True if the result is at least MIN_SAVING smaller."""
    return after <= before * (1 - MIN_SAVING)


def is_secured(doc: pymupdf.Document) -> bool:
    """Return True for password-protected files and files locked against editing."""
    # is_encrypted is False for files locked only by an owner password.
    return bool(doc.needs_pass) or doc.xref_get_key(-1, "Encrypt")[0] != "null"


def has_signature(doc: pymupdf.Document) -> bool:
    """Return True if the PDF holds a signature that re-saving would break."""
    # Certification and usage-rights signatures live in the catalog.
    if doc.xref_get_key(doc.pdf_catalog(), "Perms")[0] != "null":
        return True
    for xref in range(1, doc.xref_length()):
        if doc.xref_get_key(xref, "FT") == ("name", "/Sig") and doc.xref_get_key(
            xref, "V"
        )[0] in ("xref", "dict"):
            return True
    signature_fields = [pymupdf.PDF_WIDGET_TYPE_SIGNATURE]
    return any(
        widget.is_signed for page in doc for widget in page.widgets(signature_fields)
    )


def clear_hidden_info(doc: pymupdf.Document) -> None:
    """Empty the document information dictionary and remove the XMP packet."""
    # set_metadata({}) silently does nothing on files with object streams.
    kind, value = doc.xref_get_key(-1, "Info")
    if kind == "xref":
        doc.update_object(int(value.split()[0]), "<<>>")
    doc.del_xml_metadata()


def repair_jpeg_colorspaces(doc: pymupdf.Document) -> int:
    """Relabel JPEG images whose channel count disagrees with their color space.

    MuPDF 1.28 writes ICC gray, ICC CMYK and CalGray images as 3-channel
    JPEGs under the old color space, which renders as noise.

    Returns:
        The number of images changed.
    """
    changed = 0
    for xref in range(1, doc.xref_length()):
        if doc.xref_get_key(xref, "Subtype") != ("name", "/Image"):
            continue
        if "/DCTDecode" not in doc.xref_get_key(xref, "Filter")[1]:
            continue
        actual = _jpeg_components(doc.xref_stream_raw(xref))
        declared = _declared_components(doc, xref)
        if (
            actual in _DEVICE_SPACE_FOR_COUNT
            and declared is not None
            and actual != declared
        ):
            doc.xref_set_key(xref, "ColorSpace", _DEVICE_SPACE_FOR_COUNT[actual])
            doc.xref_set_key(xref, "Decode", "null")
            changed += 1
    return changed


def _compress(
    source: Path,
    tmp: Path,
    level: Level,
    remove_hidden_info: bool,
    size_limit_mb: float | None,
) -> FileResult:
    limit = None if size_limit_mb is None else size_limit_mb * MB
    try:
        # Reading into memory leaves no handle on the original, so a replace
        # mode can move the result over it.
        data = source.read_bytes()
    except FileNotFoundError:
        return FileResult(source, 0, None, Status.SKIPPED, SKIP_MISSING)
    except PermissionError:
        return _skipped(source, _size_or_zero(source), SKIP_IN_USE, limit)
    before = len(data)

    problem, pages = _check(data)
    if problem:
        return _skipped(source, before, problem, limit)

    tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run_pipeline(data, tmp, LEVELS[level], remove_hidden_info)
        after = tmp.stat().st_size
        if limit is not None and after > limit and level is not Level.HIGH:
            _run_pipeline(data, tmp, LEVELS[Level.HIGH], remove_hidden_info)
            after = tmp.stat().st_size
        if _page_count(tmp) != pages:
            logger.warning("Page count changed for %s; keeping the original", source)
            return _already_small(source, before, tmp, limit, size_limit_mb)
    except DamagedError:
        logger.warning("%s needed repairing while compressing; skipped", source)
        tmp.unlink(missing_ok=True)
        return _skipped(source, before, SKIP_DAMAGED, limit)
    except PYMUPDF_ERRORS:
        logger.exception("Could not compress %s; keeping the original", source)
        return _already_small(source, before, tmp, limit, size_limit_mb)

    fits_now = limit is not None and before > limit and after <= limit
    if not (saves_enough(before, after) or fits_now):
        return _already_small(source, before, tmp, limit, size_limit_mb)
    if limit is not None and after > limit:
        message = over_limit_message(after, size_limit_mb)
        return FileResult(source, before, after, Status.COMPRESSED, message, True)
    return FileResult(source, before, after, Status.COMPRESSED, COMPRESSED)


def _check(data: bytes) -> tuple[str | None, int]:
    """Return a skip reason, or None and the page count."""
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if is_secured(doc):
                return SKIP_SECURED, 0
            # A truncated file opens by repair with its pages blank.
            if doc.page_count == 0 or doc.is_repaired:
                return SKIP_DAMAGED, 0
            signed = has_signature(doc)
            # MuPDF repairs lazily, when a broken object first loads, and
            # has_signature loads them all.
            if doc.is_repaired:
                return SKIP_DAMAGED, 0
            if signed:
                return SKIP_SIGNED, 0
            return None, doc.page_count
    except PYMUPDF_ERRORS:
        return SKIP_DAMAGED, 0


def _run_pipeline(
    data: bytes, out: Path, params: LevelParams, remove_hidden_info: bool
) -> None:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        doc.rewrite_images(options=_rewrite_options(params))
        repair_jpeg_colorspaces(doc)
        doc.subset_fonts()
        if remove_hidden_info:
            clear_hidden_info(doc)
        # The steps above load every object, so a lazy repair has happened by
        # now; saving it would turn damage into blank pages.
        if doc.is_repaired:
            raise DamagedError(out)
        # garbage=4 also merges duplicates but takes seconds on long scans.
        doc.save(out, garbage=3, deflate=True, use_objstms=True)


def _page_count(path: Path) -> int:
    # The with block closes the file; an open handle would block os.replace.
    with pymupdf.open(path) as doc:
        return doc.page_count


def _rewrite_options(params: LevelParams) -> mupdf.PdfImageRewriterOptions:
    # The plain rewrite_images call only halves resolution, so a 300 dpi scan
    # would stay at 300 dpi on Low and Medium; bicubic hits the target exactly.
    # The bitonal fields keep their defaults, so 1-bit images are never touched.
    options = mupdf.PdfImageRewriterOptions()
    for kind in _IMAGE_KINDS:
        setattr(options, f"{kind}_image_subsample_method", mupdf.FZ_SUBSAMPLE_BICUBIC)
        setattr(options, f"{kind}_image_subsample_threshold", params.dpi_threshold)
        setattr(options, f"{kind}_image_subsample_to", params.dpi_target)
        setattr(options, f"{kind}_image_recompress_method", mupdf.FZ_RECOMPRESS_JPEG)
        setattr(options, f"{kind}_image_recompress_quality", str(params.quality))
    return options


def _jpeg_components(data: bytes) -> int | None:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker == 0xFF:
            index += 1
        elif marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            index += 2
        elif marker in _SOF_MARKERS:
            return data[index + 9]
        else:
            index += 2 + int.from_bytes(data[index + 2 : index + 4], "big")
    return None


def _declared_components(doc: pymupdf.Document, xref: int) -> int | None:
    kind, value = doc.xref_get_key(xref, "ColorSpace")
    if kind == "xref":
        value = doc.xref_object(int(value.split()[0]), compressed=True).strip()
        kind = "name" if value.startswith("/") else "array"
    if kind == "name":
        return _COUNT_FOR_DEVICE_SPACE.get(value)
    if kind != "array":
        return None
    family = re.match(r"\[\s*/(\w+)", value)
    if family is None:
        return None
    if family.group(1) == "ICCBased":
        profile = re.search(r"/ICCBased\s+(\d+)\s+\d+\s+R", value)
        if profile is None:
            return None
        count = doc.xref_get_key(int(profile.group(1)), "N")[1]
        return int(count) if count.isdigit() else None
    return _COUNT_FOR_FAMILY.get(family.group(1))


def _skipped(
    source: Path, before: int, message: str, limit: float | None
) -> FileResult:
    over = limit is not None and before > limit
    return FileResult(source, before, None, Status.SKIPPED, message, over)


def _already_small(
    source: Path,
    before: int,
    tmp: Path,
    limit: float | None,
    size_limit_mb: float | None,
) -> FileResult:
    tmp.unlink(missing_ok=True)
    if limit is not None and size_limit_mb is not None and before > limit:
        message = over_limit_message(before, size_limit_mb)
        return FileResult(source, before, before, Status.ALREADY_SMALL, message, True)
    return FileResult(source, before, before, Status.ALREADY_SMALL, ALREADY_SMALL)


def _size_or_zero(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _drain_warnings(source: Path | None) -> None:
    text = pymupdf.TOOLS.mupdf_warnings()
    if text:
        where = f" for {source}" if source else ""
        logger.info("MuPDF warnings%s: %s", where, text.replace("\n", " | "))
