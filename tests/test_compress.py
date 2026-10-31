import random
import re
from pathlib import Path

import pymupdf
import pytest
from conftest import BASE

from pdf_compressor.core import compress
from pdf_compressor.core.compress import (
    LEVELS,
    MB,
    LevelParams,
    Status,
    clear_hidden_info,
    compress_file,
    format_mb,
    has_signature,
    over_limit_message,
    saves_enough,
)
from pdf_compressor.core.settings import Level

DAMAGED = "Skipped: can't be opened (it may be damaged)"
COULD_NOT = "Not changed: this file couldn't be compressed"
SECURED = "Skipped: password-protected or secured"
SUBSET_NAME = re.compile(r"^[A-Z]{6}\+")


@pytest.fixture
def tmp_file(tmp_path: Path) -> Path:
    # The folder is left uncreated on purpose: compress_file makes it.
    return tmp_path / BASE / "Output" / "~1a2b3c4d.pdfc-tmp"


def run_pipeline(source: Path, out: Path, remove_hidden_info: bool = True) -> Path:
    compress._run_pipeline(
        source.read_bytes(), out, LEVELS[Level.MEDIUM], remove_hidden_info
    )
    return out


def mean_difference(first: Path, second: Path) -> float:
    with pymupdf.open(first) as a, pymupdf.open(second) as b:
        one = a[0].get_pixmap(dpi=72, colorspace=pymupdf.csRGB).samples
        two = b[0].get_pixmap(dpi=72, colorspace=pymupdf.csRGB).samples
    return sum(abs(x - y) for x, y in zip(one, two, strict=True)) / len(one)


def test_scan_pdf_compresses(scan_pdf: Path, tmp_file: Path) -> None:
    result = compress_file(scan_pdf, tmp_file, Level.MEDIUM, True, None)

    assert result.status is Status.COMPRESSED
    assert result.message == "Compressed"
    assert result.before == scan_pdf.stat().st_size
    assert result.after == tmp_file.stat().st_size
    assert result.after <= 0.9 * result.before
    assert result.over_limit is False
    with pymupdf.open(tmp_file) as doc:
        assert doc.page_count == 1
        assert "Exhibit A" in doc[0].get_text()
        image = doc[0].get_images()[0][0]
        assert doc.xref_get_key(image, "Width")[1] == "600"
        assert doc.xref_get_key(image, "Height")[1] == "750"


def test_jpeg2000_scan_compresses(jpx_pdf: Path, tmp_file: Path) -> None:
    with pymupdf.open(jpx_pdf) as doc:
        image = doc[0].get_images()[0][0]
        assert doc.xref_get_key(image, "Filter")[1] == "/JPXDecode"

    result = compress_file(jpx_pdf, tmp_file, Level.MEDIUM, True, None)

    assert result.status is Status.COMPRESSED
    with pymupdf.open(tmp_file) as doc:
        image = doc[0].get_images()[0][0]
        assert doc.xref_get_key(image, "Filter")[1] == "/DCTDecode"
        # 600 pixels across 2 inches is 300 dpi; Medium resamples to 150.
        assert doc.xref_get_key(image, "Width")[1] == "300"
        assert "Exhibit J" in doc[0].get_text()


@pytest.mark.parametrize("fixture", ["gray_icc_pdf", "cmyk_pdf", "calgray_pdf"])
def test_colorspaces_render_the_same(
    fixture: str,
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = request.getfixturevalue(fixture)

    repaired = run_pipeline(source, tmp_path / "repaired.pdf")
    assert mean_difference(source, repaired) < 5

    monkeypatch.setattr(compress, "repair_jpeg_colorspaces", lambda doc: 0)
    unrepaired = run_pipeline(source, tmp_path / "unrepaired.pdf")
    assert mean_difference(source, unrepaired) > 10


def test_bitonal_untouched(bitonal_pdf: Path, tmp_path: Path) -> None:
    out = run_pipeline(bitonal_pdf, tmp_path / "out.pdf")

    with pymupdf.open(bitonal_pdf) as before, pymupdf.open(out) as after:
        old = before[0].get_images()[0][0]
        new = after[0].get_images()[0][0]
        assert after.xref_get_key(new, "Width")[1] == "1200"
        assert after.xref_get_key(new, "Height")[1] == "1500"
        assert after.xref_get_key(new, "BitsPerComponent")[1] == "1"
        assert "DCTDecode" not in after.xref_get_key(new, "Filter")[1]
        assert after.xref_stream(new) == before.xref_stream(old)


def test_fonts_are_subset(font_pdf: Path, tmp_path: Path) -> None:
    out = run_pipeline(font_pdf, tmp_path / "out.pdf")

    with pymupdf.open(font_pdf) as before, pymupdf.open(out) as after:
        old_names = [font[3] for font in before.get_page_fonts(0)]
        new_names = [font[3] for font in after.get_page_fonts(0)]
        assert not any(SUBSET_NAME.match(name) for name in old_names)
        assert all(SUBSET_NAME.match(name) for name in new_names)
        assert after[0].get_text() == before[0].get_text()


def test_text_only_is_already_small(text_pdf: Path, tmp_file: Path) -> None:
    result = compress_file(text_pdf, tmp_file, Level.MEDIUM, True, None)

    assert result.status is Status.ALREADY_SMALL
    assert result.message == "Already small"
    assert result.after == result.before
    assert not tmp_file.exists()


def test_saves_enough() -> None:
    assert saves_enough(1000, 900) is True
    assert saves_enough(1000, 901) is False


def test_page_count_mismatch(
    scan_pdf: Path, tmp_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_count = compress._page_count
    monkeypatch.setattr(compress, "_page_count", lambda path: real_count(path) + 1)

    result = compress_file(scan_pdf, tmp_file, Level.MEDIUM, True, None)

    assert result.status is Status.FAILED
    assert result.message == COULD_NOT
    assert result.after is None
    assert not tmp_file.exists()


def test_pipeline_error_keeps_original(
    scan_pdf: Path, tmp_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_pipeline(
        data: bytes, out: Path, params: LevelParams, remove_hidden_info: bool
    ) -> None:
        out.write_bytes(b"partial")
        raise RuntimeError("simulated MuPDF failure")

    monkeypatch.setattr(compress, "_run_pipeline", failing_pipeline)

    result = compress_file(scan_pdf, tmp_file, Level.MEDIUM, True, None)

    assert result.status is Status.FAILED
    assert result.message == COULD_NOT
    assert result.after is None
    assert result.over_limit is False
    assert not tmp_file.exists()

    # Like a skip, a failure over the limit keeps its reason and turns red.
    over = compress_file(scan_pdf, tmp_file, Level.MEDIUM, True, 0.000001)
    assert over.message == COULD_NOT
    assert over.over_limit is True


def test_size_limit_retry(
    scan_pdf: Path,
    tmp_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[LevelParams] = []
    real_pipeline = compress._run_pipeline

    def spy(data: bytes, out: Path, params: LevelParams, hidden: bool) -> None:
        calls.append(params)
        real_pipeline(data, out, params, hidden)

    monkeypatch.setattr(compress, "_run_pipeline", spy)

    result = compress_file(scan_pdf, tmp_file, Level.MEDIUM, True, 0.01)
    assert calls == [LEVELS[Level.MEDIUM], LEVELS[Level.HIGH]]
    assert result.status is Status.COMPRESSED
    assert result.over_limit is True
    assert result.message == over_limit_message(result.after, 0.01)

    calls.clear()
    compress_file(scan_pdf, tmp_path / "high.tmp", Level.HIGH, True, 0.01)
    assert calls == [LEVELS[Level.HIGH]]

    calls.clear()
    roomy = compress_file(scan_pdf, tmp_path / "roomy.tmp", Level.MEDIUM, True, 100)
    assert calls == [LEVELS[Level.MEDIUM]]
    assert roomy.over_limit is False


def test_retry_keeps_the_smaller_result(
    scan_pdf: Path, tmp_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    medium = run_pipeline(scan_pdf, tmp_path / "medium.pdf").stat().st_size
    real_pipeline = compress._run_pipeline

    def high_comes_out_bigger(
        data: bytes, out: Path, params: LevelParams, hidden: bool
    ) -> None:
        # High can grow a file when it re-encodes images Medium left alone;
        # Low's bigger output stands in for that.
        if params == LEVELS[Level.HIGH]:
            params = LEVELS[Level.LOW]
        real_pipeline(data, out, params, hidden)

    monkeypatch.setattr(compress, "_run_pipeline", high_comes_out_bigger)

    result = compress_file(scan_pdf, tmp_file, Level.MEDIUM, True, 0.01)

    assert result.status is Status.COMPRESSED
    assert result.after == medium
    assert tmp_file.stat().st_size == medium


def test_limit_beats_ten_percent(
    scan_pdf: Path, tmp_file: Path, tmp_path: Path
) -> None:
    # A 4 MB attachment the pipeline can't shrink keeps the saving under 10%.
    source = tmp_path / BASE / "padded.pdf"
    with pymupdf.open(scan_pdf) as doc:
        doc.embfile_add("bulk.bin", random.Random(4).randbytes(4_000_000))
        doc.save(source, garbage=3, deflate=True, use_objstms=True, no_new_id=True)
    before = source.stat().st_size
    after = run_pipeline(source, tmp_path / "probe.pdf").stat().st_size
    # The 10% rule alone would reject this result.
    assert 0.9 * before < after < before

    limit_mb = (after + before) / 2 / MB
    result = compress_file(source, tmp_file, Level.MEDIUM, True, limit_mb)

    assert result.status is Status.COMPRESSED
    assert result.over_limit is False


def test_over_limit_message() -> None:
    assert over_limit_message(14_200_000, 10.0) == (
        "Still 14.2 MB. That's over your 10 MB limit, so it may need splitting."
    )


def test_format_mb() -> None:
    assert format_mb(14_200_000) == "14.2 MB"
    assert format_mb(412_000_000) == "412 MB"
    assert format_mb(40_000) == "0.04 MB"
    assert format_mb(10_000) == "0.01 MB"
    # Rounded to 0 MB, a small file would look empty.
    assert format_mb(9_999) == "under 0.01 MB"
    assert format_mb(3_426) == "under 0.01 MB"
    assert format_mb(0) == "0 MB"


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("encrypted_pdf", SECURED),
        ("owner_only_pdf", SECURED),
        ("damaged_pdf", DAMAGED),
        ("truncated_pdf", DAMAGED),
        ("lazy_damaged_pdf", DAMAGED),
        ("objstm_damaged_pdf", DAMAGED),
        ("signed_pdf", "Skipped: digitally signed"),
        ("zero_byte", DAMAGED),
        ("missing", "Skipped: file not found"),
    ],
)
def test_skips(
    case: str,
    message: str,
    request: pytest.FixtureRequest,
    tmp_path: Path,
    tmp_file: Path,
) -> None:
    if case == "zero_byte":
        source = tmp_path / BASE / "zero.pdf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"")
    elif case == "missing":
        source = tmp_path / BASE / "missing.pdf"
    else:
        source = request.getfixturevalue(case)

    result = compress_file(source, tmp_file, Level.MEDIUM, True, None)

    assert result.status is Status.SKIPPED
    assert result.message == message
    assert result.after is None
    assert result.over_limit is False
    assert not tmp_file.exists()


def test_skipped_file_over_limit_keeps_reason(
    encrypted_pdf: Path, tmp_file: Path
) -> None:
    result = compress_file(encrypted_pdf, tmp_file, Level.MEDIUM, True, 0.000001)

    assert result.status is Status.SKIPPED
    assert result.message == SECURED
    assert result.over_limit is True


def test_pipeline_refuses_a_file_it_had_to_repair(
    lazy_damaged_pdf: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out.pdf"

    with pytest.raises(compress.DamagedError):
        run_pipeline(lazy_damaged_pdf, out)

    assert not out.exists()


def test_icc_profile_found_at_any_generation(gray_icc_pdf: Path) -> None:
    with pymupdf.open(gray_icc_pdf) as doc:
        image = doc[0].get_images()[0][0]
        # The image points at an array object that names the profile stream.
        array = int(doc.xref_get_key(image, "ColorSpace")[1].split()[0])
        profile = re.search(r"/ICCBased\s+(\d+)", doc.xref_object(array)).group(1)
        doc.xref_set_key(image, "ColorSpace", f"[/ICCBased {profile} 1 R]")

        assert compress._declared_components(doc, image) == 1


def test_has_signature(signed_pdf: Path, empty_sig_pdf: Path, text_pdf: Path) -> None:
    for path, expected in (
        (signed_pdf, True),
        (empty_sig_pdf, False),
        (text_pdf, False),
    ):
        with pymupdf.open(path) as doc:
            assert has_signature(doc) is expected


def test_hidden_info(rich_pdf: Path, tmp_path: Path) -> None:
    cleared = run_pipeline(rich_pdf, tmp_path / "cleared.pdf", True)
    kept = run_pipeline(rich_pdf, tmp_path / "kept.pdf", False)

    with pymupdf.open(cleared) as doc:
        assert doc.metadata["title"] == ""
        assert doc.metadata["author"] == ""
        assert doc.get_xml_metadata() == ""
        assert doc.embfile_names() == ["evidence.txt"]
        assert [annot.type[1] for annot in doc[0].annots()] == ["Text"]
        assert [widget.field_name for widget in doc[0].widgets()] == ["CaseNumber"]
    with pymupdf.open(kept) as doc:
        assert doc.metadata["title"] == "Secret Title"

    alone = tmp_path / "alone.pdf"
    with pymupdf.open(rich_pdf) as doc:
        clear_hidden_info(doc)
        doc.save(alone, garbage=3, deflate=True, use_objstms=True)
    with pymupdf.open(alone) as doc:
        assert doc.metadata["title"] == ""
