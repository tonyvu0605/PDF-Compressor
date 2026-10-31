import _winapi
import msvcrt
import os
import random
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

import pymupdf
import pytest
from pymupdf import mupdf

# An n-tilde, a curly apostrophe and a letter outside cp1252, so every path
# operation is exercised with names a client folder can really have.
BASE = "Client Files \u00f1 O\u2019Brien \u1ec5"

SYSTEM_VARS = (
    "WINDIR",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramData",
    "APPDATA",
    "LOCALAPPDATA",
)


@pytest.fixture(autouse=True)
def isolated_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the home folder and the system folders into tmp_path."""
    # tmp_path normally sits inside the real %LOCALAPPDATA%, which is blocked.
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "Home"))
    for var in SYSTEM_VARS:
        monkeypatch.setenv(var, str(tmp_path / "System" / var))


def make_junction(link: Path, target: Path) -> None:
    """Create a directory junction, which needs no admin rights."""
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(link))


def can_symlink(folder: Path) -> bool:
    """Return True if this account may create symlinks."""
    target = folder / "symlink-probe-target.txt"
    link = folder / "symlink-probe.txt"
    target.write_text("probe", encoding="utf-8")
    try:
        link.symlink_to(target)
    except OSError:
        return False
    else:
        link.unlink()
        return True
    finally:
        target.unlink()


WORDS = [
    "plaintiff",
    "defendant",
    "motion",
    "court",
    "order",
    "hearing",
    "exhibit",
    "filed",
    "counsel",
    "judgment",
    "evidence",
    "witness",
    "record",
    "appeal",
    "brief",
    "statute",
    "claim",
    "damages",
    "party",
    "notice",
    "served",
]

XMP_PACKET = (
    '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/"'
    ' dc:format="application/pdf"/></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
)


def _words(rng: random.Random, count: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(count))


def _save(doc: pymupdf.Document, path: Path, **options: object) -> Path:
    """Save the way the fixtures need: compact, and byte-identical on rebuild."""
    path.parent.mkdir(parents=True, exist_ok=True)
    standard = {"garbage": 3, "deflate": True, "use_objstms": True, "no_new_id": True}
    doc.save(path, **(standard | options))
    doc.close()
    return path


def build_scan_pdf(path: Path) -> Path:
    """Write a one-page scan: a 300 dpi RGB JPEG of text, plus one real text line."""
    rng = random.Random(1)
    source = pymupdf.open()
    source_page = source.new_page(width=4 * 72, height=5 * 72)
    y = 30.0
    while y < source_page.rect.height - 20:
        source_page.insert_text((20, y), _words(rng, 9), fontsize=10)
        y += 14
    pixmap = source_page.get_pixmap(dpi=300)
    source.close()
    # Speckle keeps the JPEG from being trivially small, like a real scan.
    for _ in range(4000):
        value = rng.randrange(120, 256)
        position = (rng.randrange(pixmap.width), rng.randrange(pixmap.height))
        pixmap.set_pixel(*position, (value, value, value))
    doc = pymupdf.open()
    page = doc.new_page(width=4 * 72, height=5 * 72)
    page.insert_image(page.rect, stream=pixmap.tobytes("jpeg", jpg_quality=90))
    page.insert_text((20, 352), "Exhibit A", fontsize=8)
    return _save(doc, path)


def build_text_pdf(path: Path) -> Path:
    """Write three pages of text that the pipeline can't shrink further."""
    rng = random.Random(2)
    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page()
        lines = [_words(rng, 11) for _ in range(43)]
        page.insert_text((72, 72), "\n".join(lines), fontsize=11, lineheight=15 / 11)
    # rewrite_images rewrites every content stream, the way the pipeline will.
    doc.rewrite_images()
    return _save(doc, path)


def _gradient_pixmap(colorspace: pymupdf.Colorspace) -> pymupdf.Pixmap:
    rng = random.Random(3)
    size = 600
    base = [x * 230 // size for x in range(size) for _ in range(colorspace.n)]
    # Noise on every pixel keeps the image from compressing so well that
    # MuPDF decides a JPEG would not be smaller and leaves it alone.
    small_noise = bytes(value % 25 for value in range(256))
    rows = []
    for _ in range(size):
        noise = rng.randbytes(len(base)).translate(small_noise)
        rows.append(bytes(map(sum, zip(base, noise, strict=True))))
    return pymupdf.Pixmap(colorspace, size, size, b"".join(rows), False)


def _image_pdf(
    path: Path, colorspace: pymupdf.Colorspace, color_space_object: str | None
) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=216, height=216)
    # A 600 pixel image in a 2 inch square is 300 dpi.
    xref = page.insert_image(
        pymupdf.Rect(36, 36, 180, 180), pixmap=_gradient_pixmap(colorspace)
    )
    if color_space_object:
        doc.xref_set_key(xref, "ColorSpace", color_space_object)
    return _save(doc, path)


def build_jpx_pdf(path: Path) -> Path:
    """Write a page with a 300 dpi JPEG 2000 image, as Acrobat's optimizer saves."""
    pixmap = _gradient_pixmap(pymupdf.csRGB)
    # PyMuPDF's own writers have no JPEG 2000 option, so ask MuPDF directly.
    encoded = mupdf.fz_new_buffer_from_pixmap_as_jpx(
        pixmap.this, mupdf.FzColorParams(), 80
    )
    doc = pymupdf.open()
    page = doc.new_page(width=216, height=216)
    page.insert_image(
        pymupdf.Rect(36, 36, 180, 180), stream=bytes(mupdf.fz_buffer_extract(encoded))
    )
    page.insert_text((36, 200), "Exhibit J", fontsize=10)
    return _save(doc, path)


def build_bitonal_pdf(path: Path) -> Path:
    """Write a page with one 1-bit image of mostly white rows."""
    width, height = 1200, 1500
    white = bytes([0xFF]) * (width // 8)
    black = bytes(width // 8)
    data = b"".join(black if row % 50 == 0 else white for row in range(height))
    doc = pymupdf.open()
    page = doc.new_page(width=4 * 72, height=5 * 72)
    xref = doc.get_new_xref()
    doc.update_object(
        xref,
        f"<</Type/XObject/Subtype/Image/Width {width}/Height {height}"
        "/BitsPerComponent 1/ColorSpace/DeviceGray>>",
    )
    doc.update_stream(xref, data)
    page.insert_image(page.rect, xref=xref)
    return _save(doc, path)


def build_font_pdf(path: Path) -> Path:
    """Write a page whose text uses a fully embedded font."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="F0", fontbuffer=pymupdf.Font("helv").buffer)
    page.insert_text((72, 72), "Smith v. Jones, Exhibit 12", fontname="F0")
    return _save(doc, path)


def build_encrypted_pdf(path: Path, user_password: str) -> Path:
    """Write an AES-256 PDF; an empty user password locks only editing."""
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Encrypted fixture")
    return _save(
        doc,
        path,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw=user_password,
        owner_pw="owner",
        permissions=pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_ACCESSIBILITY,
    )


def _six_pages() -> pymupdf.Document:
    doc = pymupdf.open()
    for number in range(6):
        doc.new_page().insert_text((72, 72), f"Page {number + 1}")
    return doc


def _load_every_object(doc: pymupdf.Document) -> None:
    for xref in range(1, doc.xref_length()):
        doc.xref_get_key(xref, "Type")


def build_truncated_pdf(path: Path) -> Path:
    """Write a PDF cut short: it opens only by repair, with its last pages blank."""
    doc = _six_pages()
    last_content = doc[5].get_contents()[0]
    data = doc.tobytes()
    doc.close()
    # The last page's content is the last object, so the cut loses only it
    # and the cross-reference table after it.
    cut = data[: data.index(f"\n{last_content} 0 obj".encode()) + 1]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cut)
    with pymupdf.open(stream=cut, filetype="pdf") as check:
        assert check.is_repaired
        assert any(not page.get_text().strip() for page in check)
    return path


def build_lazy_damaged_pdf(path: Path) -> Path:
    """Write a PDF whose damage MuPDF repairs only once the bad object loads."""
    doc = _six_pages()
    content = doc[2].get_contents()[0]
    data = bytearray(doc.tobytes())
    doc.close()
    start = data.index(f"\n{content} 0 obj".encode()) + 1
    end = data.index(b"endobj", start) + len(b"endobj")
    data[start:end] = bytes(end - start)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(data))
    with pymupdf.open(stream=bytes(data), filetype="pdf") as check:
        assert not check.is_repaired
        _load_every_object(check)
        assert check.is_repaired
    return path


def build_objstm_damaged_pdf(path: Path) -> Path:
    """Write a PDF with object streams, one of them corrupted."""
    doc = _six_pages()
    data = bytearray(doc.tobytes(garbage=3, deflate=True, use_objstms=True))
    doc.close()
    body = data.index(b"stream", data.index(b"/ObjStm")) + len(b"stream")
    body += 2 if data[body : body + 2] == b"\r\n" else 1
    data[body + 2 : body + 10] = bytes(8)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(data))
    return path


def build_rich_pdf(path: Path) -> Path:
    """Write a PDF with metadata, XMP, an attachment, an annotation and a field."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Rich fixture")
    doc.set_metadata(
        {
            "title": "Secret Title",
            "author": "Jane Lawyer",
            "subject": "Smith v. Jones",
            "keywords": "draft",
            "creator": "Word",
            "producer": "Acrobat",
        }
    )
    doc.set_xml_metadata(XMP_PACKET)
    doc.embfile_add("evidence.txt", b"attachment bytes")
    page.add_text_annot((300, 300), "Reviewer note")
    field = pymupdf.Widget()
    field.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    field.field_name = "CaseNumber"
    field.field_value = "2024-CV-0042"
    field.rect = pymupdf.Rect(72, 400, 300, 420)
    page.add_widget(field)
    return _save(doc, path)


def build_signature_pdf(path: Path, signed: bool) -> Path:
    """Write a PDF with one signature field, signed or empty."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Signed document")
    value = ""
    if signed:
        signature = doc.get_new_xref()
        doc.update_object(
            signature,
            "<</Type/Sig/Filter/Adobe.PPKLite/SubFilter/adbe.pkcs7.detached"
            "/ByteRange[0 100 200 50]/Contents<00112233>>>",
        )
        value = f"/V {signature} 0 R"
    field = doc.get_new_xref()
    doc.update_object(
        field,
        f"<</Type/Annot/Subtype/Widget/FT/Sig/T(Signature1){value}"
        f"/Rect[72 600 272 650]/F 4/P {page.xref} 0 R>>",
    )
    doc.xref_set_key(page.xref, "Annots", f"[{field} 0 R]")
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"<</Fields[{field} 0 R]>>")
    return _save(doc, path)


@pytest.fixture
def pdf_dir(tmp_path: Path) -> Path:
    return tmp_path / BASE / "Fixtures"


@pytest.fixture
def scan_pdf(pdf_dir: Path) -> Path:
    return build_scan_pdf(pdf_dir / "scan.pdf")


@pytest.fixture
def text_pdf(pdf_dir: Path) -> Path:
    return build_text_pdf(pdf_dir / "text.pdf")


@pytest.fixture
def gray_icc_pdf(pdf_dir: Path) -> Path:
    return _image_pdf(pdf_dir / "gray icc.pdf", pymupdf.csGRAY, None)


@pytest.fixture
def cmyk_pdf(pdf_dir: Path) -> Path:
    return _image_pdf(pdf_dir / "cmyk.pdf", pymupdf.csCMYK, None)


@pytest.fixture
def calgray_pdf(pdf_dir: Path) -> Path:
    calgray = "[/CalGray <</WhitePoint [0.9505 1 1.089]>>]"
    return _image_pdf(pdf_dir / "calgray.pdf", pymupdf.csGRAY, calgray)


@pytest.fixture
def jpx_pdf(pdf_dir: Path) -> Path:
    return build_jpx_pdf(pdf_dir / "jpx.pdf")


@pytest.fixture
def bitonal_pdf(pdf_dir: Path) -> Path:
    return build_bitonal_pdf(pdf_dir / "bitonal.pdf")


@pytest.fixture
def font_pdf(pdf_dir: Path) -> Path:
    return build_font_pdf(pdf_dir / "font.pdf")


@pytest.fixture
def encrypted_pdf(pdf_dir: Path) -> Path:
    return build_encrypted_pdf(pdf_dir / "encrypted.pdf", user_password="secret")


@pytest.fixture
def owner_only_pdf(pdf_dir: Path) -> Path:
    return build_encrypted_pdf(pdf_dir / "owner only.pdf", user_password="")


@pytest.fixture
def damaged_pdf(pdf_dir: Path) -> Path:
    path = pdf_dir / "damaged.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n" + b"\x00garbage" * 50)
    return path


@pytest.fixture
def truncated_pdf(pdf_dir: Path) -> Path:
    return build_truncated_pdf(pdf_dir / "truncated.pdf")


@pytest.fixture
def lazy_damaged_pdf(pdf_dir: Path) -> Path:
    return build_lazy_damaged_pdf(pdf_dir / "lazy damaged.pdf")


@pytest.fixture
def objstm_damaged_pdf(pdf_dir: Path) -> Path:
    return build_objstm_damaged_pdf(pdf_dir / "objstm damaged.pdf")


@pytest.fixture
def rich_pdf(pdf_dir: Path) -> Path:
    return build_rich_pdf(pdf_dir / "rich.pdf")


@pytest.fixture
def signed_pdf(pdf_dir: Path) -> Path:
    return build_signature_pdf(pdf_dir / "signed.pdf", signed=True)


@pytest.fixture
def empty_sig_pdf(pdf_dir: Path) -> Path:
    return build_signature_pdf(pdf_dir / "empty signature.pdf", signed=False)


@contextmanager
def hold_open(path: Path) -> Iterator[BinaryIO]:
    """Keep a file open the way a PDF viewer does: reads work, replacing fails."""
    with path.open("rb") as file:
        yield file


@contextmanager
def lock_bytes(path: Path) -> Iterator[None]:
    """Lock every byte of a file, so reading it fails until the block ends."""
    size = path.stat().st_size
    fd = os.open(path, os.O_RDWR)
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, size)
        try:
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, size)
    finally:
        os.close(fd)
