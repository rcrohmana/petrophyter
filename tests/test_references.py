"""Reference registry, BibTeX file, method texts, dialog and Method & Reference box."""

import os
import re
import warnings
from pathlib import Path

import pytest

from modules import references
from modules.lrlc import SHIPPED_METHODS
from modules.lrlc.methods import METHOD_TEXT, MethodInfo
from modules.references import REFERENCES

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal box would block the offscreen test run; fail loudly instead."""
    from PyQt6.QtWidgets import QMessageBox

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


# ------------------------------------------------------------------ registry


def test_keys_unique_and_match_entries():
    assert all(key == ref.key for key, ref in REFERENCES.items())
    assert len(references._ENTRIES) == len(REFERENCES)


def test_statuses_and_kinds_valid():
    for ref in REFERENCES.values():
        assert ref.status in references.VALID_STATUSES, ref.key
        assert ref.kind in references.VALID_KINDS, ref.key


def test_verified_entries_have_doi_or_url():
    verified = [r for r in REFERENCES.values() if r.status == "verified"]
    assert {r.key for r in verified} == {
        "liu2023", "ashfaq_us11709287", "zhao2022", "boyd1995", "worthington2000",
        "zemanek1989", "pickett1966", "buckles1965", "archie1942", "waxman1968", "clavier1984",
        "poupon1954", "hagiwara_us4739255", "hagiwara1995", "hagiwara1997", "thomas1975",
        "clavier1976", "hill1979", "juhasz1981", "borai1987", "arps1953", "doll1949",
        "anderson2001", "thadani1981",
    }
    for ref in verified:
        assert ref.doi or ref.url, ref.key


def test_seed_table_complete():
    assert len(REFERENCES) == 40


def test_refs_for_unknown_key_raises():
    assert [r.key for r in references.refs_for("liu2023", "boyd1995")] == ["liu2023", "boyd1995"]
    with pytest.raises(KeyError):
        references.refs_for("nobody1900")


def test_format_short():
    assert references.format_short("hagiwara1997") == "Hagiwara (1997)"
    assert references.format_short("boyd1995") == "Boyd et al. (1995)"
    assert references.format_short("morris1967") == "Morris and Biggs (1967)"
    assert references.format_short("clavier1984") == "Clavier, Coates and Dumanoir (1984)"


def test_format_full_marks_unverified_only():
    assert references.format_full("simandoux1963").endswith("(citation details to be confirmed)")
    full = references.format_full("liu2023")
    assert "to be confirmed" not in full
    assert "10.1515/geo-2022-0520" in full
    assert all(references.format_full(k) for k in REFERENCES)


def test_bibtex_shape_and_determinism():
    one = references.to_bibtex("liu2023")
    assert one.startswith("@article{liu2023,")
    assert "doi = {10.1515/geo-2022-0520}" in one
    assert "note = {verified}" in one
    assert "\r" not in one
    allbib = references.to_bibtex_all()
    assert allbib == references.to_bibtex_all()
    keys = re.findall(r"^@\w+\{([^,]+),", allbib, flags=re.M)
    assert keys == sorted(REFERENCES)
    assert "@misc{ashfaq_us11709287," in allbib


def test_bib_file_in_sync():
    path = ROOT / "docs" / "references.bib"
    on_disk = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert on_disk == references.to_bibtex_all()


def test_cli_writes_identical_file(tmp_path):
    target = tmp_path / "out.bib"
    assert references.main(["--bib", str(target)]) == 0
    raw = target.read_bytes()
    assert b"\r" not in raw
    assert raw.decode("utf-8") == references.to_bibtex_all()


# ------------------------------------------------------------- shipped methods


def test_shipped_method_keys_exist():
    for method, keys in SHIPPED_METHODS.items():
        references.refs_for(*keys)  # KeyError on an unknown key


def test_method_text_refs_exist_and_match_shipped():
    for name, info in METHOD_TEXT.items():
        assert isinstance(info, MethodInfo)
        references.refs_for(*info.refs)
        if name in SHIPPED_METHODS:
            assert info.refs == SHIPPED_METHODS[name], name
    assert set(METHOD_TEXT) == {
        "screening", "rt_cutoff", "bvw", "buckles", "pickett", "rt_chain", "thomas_stieber",
        "laminated", "pyrite", "qv", "variable_mn", "invasion"}


def test_method_text_content():
    assert (
        "Thresholds are design defaults, calibrate per field; Boyd 1995 and Worthington 2000 "
        "are the qualitative basis." in METHOD_TEXT["screening"].assumptions
    )
    phase_id = re.compile(r"\b(L[1-4]|P[0-9])\b")
    for name, info in METHOD_TEXT.items():
        text = " ".join([info.title, info.equation, info.equation_after, info.assumptions,
                         info.limits] + [" ".join(row) for row in info.criteria])
        assert text.isascii(), name
        assert not phase_id.search(text), name
        assert info.equation and info.assumptions and info.limits, name


def test_shipped_references_report():
    """Under RELEASE=1 list unverified shipped keys as a warning; never fails or skips."""
    unverified = sorted(
        {k for keys in SHIPPED_METHODS.values() for k in keys if REFERENCES[k].status != "verified"}
    )
    if os.environ.get("RELEASE") == "1" and unverified:
        warnings.warn(
            "Shipped references still to verify: " + ", ".join(unverified), UserWarning
        )


# --------------------------------------------------------------------- widgets


def test_references_dialog_lists_groups_and_exports(qtbot, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QFileDialog
    from ui.widgets.references_dialog import ReferencesDialog

    dlg = ReferencesDialog()
    qtbot.addWidget(dlg)
    text = dlg.browser.toPlainText()
    assert dlg.browser.isReadOnly()
    for group in ("LRLC screening", "Rt cutoff", "Pickett plot", "Saturation-height"):
        assert group in text
    assert "Boyd et al. (1995)" in text
    assert "(citation details to be confirmed)" in text
    assert "https://doi.org/10.1515/geo-2022-0520" in dlg.browser.toHtml()
    assert dlg.export_btn.text() == "Export BibTeX…"

    target = tmp_path / "refs.bib"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    dlg.export_btn.click()
    assert target.read_bytes().decode("utf-8") == references.to_bibtex_all()

    cancelled = tmp_path / "none.bib"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    dlg.export_btn.click()
    assert not cancelled.exists()


def test_method_box_shows_method(qtbot):
    from ui.widgets.method_box import MethodReferenceBox

    box = MethodReferenceBox()
    qtbot.addWidget(box)
    assert box.title() == "Method && Reference"  # drawn as "Method & Reference"
    box.set_method(METHOD_TEXT["rt_cutoff"])
    assert "RT_CUT" in box.equation.toPlainText()  # the copyable plain-text form, not shown
    assert box.equation.isHidden()
    assert box.equation_view.lines == METHOD_TEXT["rt_cutoff"].equation_tex
    assert box.link.text() == "Assumptions, limits and references"
    assert box.key == "rt_cutoff"
    assert not hasattr(box, "assumptions") and not hasattr(box, "limits")
    cites = box.citations.text()
    assert "Liu Chenglin et al. (2023)" in cites
    assert "Liu Chenglin et al. (2023) (to verify)" not in cites
    assert "Archie (1942); " in cites
    assert "Simandoux (1963) (to verify)" in cites
    box.set_method(METHOD_TEXT["rt_chain"])
    assert box.citations.isHidden()
