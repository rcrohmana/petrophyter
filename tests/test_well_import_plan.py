"""Pure import-plan layer for multi-well tops and core files (spec §3.7): no Qt widgets."""

import os

import pandas as pd
import pytest

from modules.well_import import (
    ImportOptions, WellRef, build_import_plan, build_parts, import_record,
    parse_import_file, well_refs,
)

M_TO_FT = 3.28084


def write(tmp_path, text, name="file.csv"):
    path = tmp_path / name
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return str(path)


def ref(name, **kw):
    info = kw.pop("well_info", {"well_name": name})
    kw.setdefault("log_top", 0.0)
    kw.setdefault("log_bottom", 10000.0)
    return WellRef(key=f"WELL:{name}", display_name=name, well_info=info, **kw)


def plan_for(path, wells, kind="tops", **opts):
    options = ImportOptions(kind=kind, **opts)
    parsed = parse_import_file(path, options)
    return build_import_plan(parsed, path, wells, options)


TOPS = """
Well,Formation,Top (ft),Bottom (ft)
BKS-01,A,1000,1100
BKS-01,B,1100,1200
bks 01,C,1200,1300
BKS-02,A,2000,2100
"""


# ---------------------------------------------------------------------------
# Grouping and matching
# ---------------------------------------------------------------------------
def test_spellings_form_one_row(tmp_path):
    plan = plan_for(write(tmp_path, TOPS), [ref("BKS-01"), ref("BKS-02")])
    assert [r.file_well for r in plan.rows] == ["BKS-01", "BKS-02"]
    first = plan.rows[0]
    assert first.spellings == ["BKS-01", "bks 01"]
    assert first.rows == 3
    assert [f.name for f in first.part.formations] == ["A", "B", "C"]
    assert first.status == "matched" and first.match_how == "name"
    assert first.target_key == "WELL:BKS-01"
    assert first.depth_range == (1000.0, 1300.0)
    assert plan.blockers() == []
    assert plan.changes() == 2
    assert plan.wells_not_in_file == []


def test_match_reasons_uwi_api_name(tmp_path):
    uwi = write(tmp_path, "UWI,Formation,Top (ft)\n100/01,A,10\n", "uwi.csv")
    api = write(tmp_path, "API,Formation,Top (ft)\n42-123,A,10\n", "api.csv")
    wells = [ref("W1", well_info={"uwi": "100/01", "well_name": "W1"}),
             ref("W2", well_info={"api": "42-123", "well_name": "W2"}),
             ref("W3", well_info={"well_name": "X-9"})]
    assert plan_for(uwi, wells).rows[0].match_how == "uwi"
    assert plan_for(uwi, wells).rows[0].target_key == "WELL:W1"
    assert plan_for(api, wells).rows[0].match_how == "api"
    assert plan_for(api, wells).rows[0].target_key == "WELL:W2"
    # A well name in a UWI column is retried as a name.
    named = write(tmp_path, "UWI,Formation,Top (ft)\nx-9,A,10\n", "named.csv")
    row = plan_for(named, wells).rows[0]
    assert row.target_key == "WELL:W3" and row.match_how == "name"


def test_no_match_skips(tmp_path):
    plan = plan_for(write(tmp_path, TOPS), [ref("OTHER")])
    assert all(r.status == "no_match" and r.action == "skip" for r in plan.rows)
    assert plan.wells_not_in_file == ["OTHER"]
    assert plan.blockers() == ["No well would receive data"]


def test_ambiguous_blocks_until_target_set(tmp_path):
    path = write(tmp_path, "Well,Formation,Top (ft)\nA,X,10\n")
    one, two = ref("A"), ref("A")
    two.key = "WELL:A#2"
    plan = plan_for(path, [one, two])
    row = plan.rows[0]
    assert row.status == "ambiguous" and row.target_key is None
    assert row.candidates == ["WELL:A", "WELL:A#2"]
    assert any("Choose the well" in b for b in plan.blockers())
    plan.set_target(0, "WELL:A#2")
    assert row.status == "matched" and row.match_how == "manual"
    assert row.action == "assign"
    assert plan.blockers() == []
    plan.set_target(0, None)
    assert row.action == "skip" and row.status == "no_match"


def test_two_rows_one_well_is_a_blocker(tmp_path):
    path = write(tmp_path, "Well,Formation,Top (ft)\nA,X,10\nB,X,10\n")
    plan = plan_for(path, [ref("A"), ref("B")])
    assert plan.blockers() == []
    plan.set_target(1, "WELL:A")
    assert any("same well" in b for b in plan.blockers())
    assert all(any("Also assigned" in n for n in r.notes) for r in plan.rows)
    plan.set_action(1, "skip")
    assert plan.blockers() == []
    assert not any("Also assigned" in n for n in plan.rows[0].notes)


# ---------------------------------------------------------------------------
# Existing data (D5)
# ---------------------------------------------------------------------------
def test_default_action_keep_or_replace(tmp_path):
    path = write(tmp_path, "Well,Formation,Top (ft)\nA,X,10\nB,X,10\nC,X,10\n")
    wells = [ref("A"),
             ref("B", existing_count=4, existing_path=str(tmp_path / "other.csv")),
             ref("C", existing_count=12, existing_path=os.path.join(
                 str(tmp_path), ".", "file.csv"))]
    rows = plan_for(path, wells).rows
    assert [r.action for r in rows] == ["assign", "keep", "replace"]
    assert rows[0].existing == "none"
    assert rows[1].existing == "4 formations (other.csv)"
    assert rows[2].existing == "12 formations (file.csv)"


def test_set_action_normalises(tmp_path):
    path = write(tmp_path, "Well,Formation,Top (ft)\nA,X,10\nB,X,10\n")
    plan = plan_for(path, [ref("A"), ref("B", existing_count=2)])
    plan.set_action(0, "replace")
    assert plan.rows[0].action == "assign"
    plan.set_action(1, "replace")
    assert plan.rows[1].action == "replace"
    plan.set_action(1, "keep")
    assert plan.changes() == 1
    with pytest.raises(ValueError):
        plan.set_action(0, "explode")


# ---------------------------------------------------------------------------
# Fill-down (D6)
# ---------------------------------------------------------------------------
MERGED = """
Well,Formation,Top (ft)
W1,A,100
,B,200
W2,A,100
,B,200
"""


def test_fill_down_default_on_for_merged_cells(tmp_path):
    plan = plan_for(write(tmp_path, MERGED), [ref("W1"), ref("W2")])
    assert plan.parsed.fill_down is True
    assert [r.rows for r in plan.rows] == [2, 2]
    assert plan.no_well_rows == []


def test_fill_down_can_be_switched_off(tmp_path):
    plan = plan_for(write(tmp_path, MERGED), [ref("W1"), ref("W2")], fill_down=False)
    assert plan.parsed.fill_down is False
    assert [r.rows for r in plan.rows] == [1, 1]
    assert len(plan.no_well_rows) == 2


def test_fill_down_default_off_otherwise(tmp_path):
    text = "Well,Formation,Top (ft)\n,A,100\nW1,B,200\n"
    plan = plan_for(write(tmp_path, text), [ref("W1")])
    assert plan.parsed.fill_down is False
    assert len(plan.no_well_rows) == 1
    assert any("without a well" in n for n in plan.notes)


# ---------------------------------------------------------------------------
# Last formation bottom (D4)
# ---------------------------------------------------------------------------
NO_BOTTOM = "Well,Formation,Top (ft)\nW1,A,100\nW1,B,200\n"


def test_last_bottom_log_bottom_extends_inferred(tmp_path):
    wells = [ref("W1", log_bottom=500.0)]
    plan = plan_for(write(tmp_path, NO_BOTTOM), wells)
    part = build_parts(plan, wells)["WELL:W1"]
    a, b = part.formations
    assert (a.bottom_depth, b.bottom_depth) == (200.0, 500.0)
    assert b.thickness == 300.0
    # The plan's own part is not modified.
    assert plan.rows[0].part.formations[1].bottom_depth == 200.0


def test_last_bottom_next_top_leaves_it(tmp_path):
    wells = [ref("W1", log_bottom=500.0)]
    plan = plan_for(write(tmp_path, NO_BOTTOM), wells, last_bottom="next_top")
    part = build_parts(plan, wells)["WELL:W1"]
    assert part.formations[1].bottom_depth == 200.0


def test_explicit_bottoms_are_untouched(tmp_path):
    text = "Well,Formation,Top (ft),Bottom (ft)\nW1,A,100,150\nW1,B,200,250\n"
    wells = [ref("W1", log_bottom=500.0)]
    plan = plan_for(write(tmp_path, text), wells)
    part = build_parts(plan, wells)["WELL:W1"]
    assert part.formations[1].bottom_depth == 250.0


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
UNDETECTED = "Well,Formation,Top\nW1,A,100\nW1,B,200\n"


def test_unit_undetected_blocks_and_choice_unblocks(tmp_path):
    path = write(tmp_path, UNDETECTED)
    wells = [ref("W1")]
    plan = plan_for(path, wells)
    assert plan.effective_unit is None
    assert plan.blockers() == ["Choose the depth unit (M or FT)"]
    assert plan.rows[0].depth_range is None
    with pytest.raises(ValueError):
        build_parts(plan, wells)

    plan = plan_for(path, wells, depth_unit="M", last_bottom="next_top")
    assert plan.effective_unit == "M" and plan.blockers() == []
    assert plan.rows[0].depth_range == pytest.approx((100 * M_TO_FT, 200 * M_TO_FT))
    part = build_parts(plan, wells)["WELL:W1"]
    assert part.formations[0].top_depth == pytest.approx(100 * M_TO_FT)
    assert part.depth_unit == "FT" and part.converted_to_feet

    plan = plan_for(path, wells, depth_unit="FT")
    assert build_parts(plan, wells)["WELL:W1"].formations[0].top_depth == 100.0


def test_detected_unit_is_used(tmp_path):
    text = "Well,Formation,Top (m)\nW1,A,100\n"
    wells = [ref("W1")]
    plan = plan_for(write(tmp_path, text), wells, last_bottom="next_top")
    assert plan.effective_unit == "M"
    part = build_parts(plan, wells)["WELL:W1"]
    assert part.formations[0].top_depth == pytest.approx(100 * M_TO_FT)


def test_unit_fit_marks_metres(tmp_path):
    text = "Well,Formation,Top\nW1,A,1000\nW1,B,1400\n"
    wells = [ref("W1", log_top=3200.0, log_bottom=5000.0)]
    plan = plan_for(write(tmp_path, text), wells)
    row = plan.rows[0]
    assert row.unit_fit == "M"
    assert row.coverage is None            # unit not decided yet
    plan = plan_for(write(tmp_path, text), wells, depth_unit="M")
    assert plan.rows[0].unit_fit == "M"
    assert plan.rows[0].coverage == 1.0 and plan.rows[0].coverage_note is None
    plan = plan_for(write(tmp_path, text), wells, depth_unit="FT")
    assert plan.rows[0].coverage == 0.0
    assert "outside" in plan.rows[0].coverage_note


def test_unit_fit_ambiguous_when_both_overlap(tmp_path):
    text = "Well,Formation,Top\nW1,A,1000\n"
    plan = plan_for(write(tmp_path, text), [ref("W1", log_top=0, log_bottom=9000)])
    assert plan.rows[0].unit_fit is None


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
CORE = """
Well,Depth (ft),Porosity,Perm
W1,1000,15,10
W1,1001,20,12
W2,1000,0.15,5
W2,1001,0.2,6
"""


def test_core_porosity_scale_per_well(tmp_path):
    plan = plan_for(write(tmp_path, CORE), [ref("W1"), ref("W2")], kind="core")
    assert [r.porosity_scale for r in plan.rows] == ["percent", "fraction"]
    assert any("differs" in n for n in plan.notes)
    parts = build_parts(plan, plan.wells)
    assert parts["WELL:W1"].data[parts["WELL:W1"].porosity_col].tolist() == pytest.approx([0.15, 0.2])
    assert parts["WELL:W2"].data[parts["WELL:W2"].porosity_col].tolist() == pytest.approx([0.15, 0.2])


def test_core_porosity_override(tmp_path):
    wells = [ref("W1"), ref("W2")]
    plan = plan_for(write(tmp_path, CORE), wells, kind="core",
                    porosity_scales={"W2": "percent"})
    assert [r.porosity_scale for r in plan.rows] == ["percent", "percent"]
    part = build_parts(plan, wells)["WELL:W2"]
    assert part.data[part.porosity_col].tolist() == pytest.approx([0.0015, 0.002])
    assert import_record(plan, plan.rows[1])["porosity_scale"] == "percent"
    # A file read without the override gets it applied when the plan is built.
    options = ImportOptions(kind="core", porosity_scales={"W1": "fraction"})
    parsed = parse_import_file(plan.path, ImportOptions(kind="core"))
    again = build_import_plan(parsed, plan.path, wells, options)
    assert again.rows[0].porosity_scale == "fraction"
    assert any("above 1" in n for n in again.rows[0].notes)


def test_core_metres_detected_and_overridden(tmp_path):
    text = "Well,Depth (m),Porosity\nW1,1000,0.1\n"
    wells = [ref("W1")]
    plan = plan_for(write(tmp_path, text), wells, kind="core")
    assert plan.effective_unit == "M"
    assert plan.rows[0].depth_range == pytest.approx((1000 * M_TO_FT,) * 2)
    part = build_parts(plan, wells)["WELL:W1"]
    assert part.data[part.depth_col].iloc[0] == pytest.approx(1000 * M_TO_FT)
    # The user says the numbers are feet after all.
    plan = plan_for(write(tmp_path, text), wells, kind="core", depth_unit="FT")
    part = build_parts(plan, wells)["WELL:W1"]
    assert part.data[part.depth_col].iloc[0] == pytest.approx(1000.0)


def test_core_undetected_unit_chosen_as_metres(tmp_path):
    text = "Well,Depth,Porosity\nW1,1000,0.1\n"
    wells = [ref("W1")]
    assert plan_for(write(tmp_path, text), wells, kind="core").blockers() == [
        "Choose the depth unit (M or FT)"]
    plan = plan_for(write(tmp_path, text), wells, kind="core", depth_unit="M")
    part = build_parts(plan, wells)["WELL:W1"]
    assert part.data[part.depth_col].iloc[0] == pytest.approx(1000 * M_TO_FT)


def test_core_tvd_blocker(tmp_path):
    text = "Well,TVD (ft),Porosity\nW1,1000,0.1\n"
    wells = [ref("W1")]
    plan = plan_for(write(tmp_path, text), wells, kind="core")
    assert plan.blockers() == ["Confirm that TVD core depths may be used"]
    with pytest.raises(ValueError):
        build_parts(plan, wells)
    plan = plan_for(write(tmp_path, text), wells, kind="core", tvd_confirmed=True)
    assert plan.blockers() == []
    assert "WELL:W1" in build_parts(plan, wells)


# ---------------------------------------------------------------------------
# Zone impact, excluded rows
# ---------------------------------------------------------------------------
def test_zone_impact_notes(tmp_path):
    path = write(tmp_path, "Well,Formation,Top (ft)\nW1,Alpha,100\nW1,Beta,200\n")
    wells = [ref("W1", existing_count=2, existing_path=path,
                 zones_with_params=["ALPHA", "GAMMA"],
                 selected_formations=["Gamma ", "alpha"])]
    row = plan_for(path, wells).rows[0]
    assert row.action == "replace"
    assert row.zone_impact == ["zone parameters for GAMMA will no longer apply",
                               "Gamma  will be removed from the analysis scope"]
    # Keeping the existing tops changes nothing.
    wells[0].existing_path = None
    row = plan_for(path, wells).rows[0]
    assert row.action == "keep" and row.zone_impact == []


def test_excluded_rows_counted_per_well(tmp_path):
    text = """
Well,Formation,Top (ft)
W1,A,100
W1,B,n/a
W2,A,100
,C,300
W2,D,
"""
    plan = plan_for(write(tmp_path, text), [ref("W1"), ref("W2")], fill_down=False)
    w1, w2 = plan.rows
    assert [(l, r.split()[0]) for l, r in w1.excluded] == [(3, "non-numeric")]
    assert [l for l, _ in w2.excluded] == [6]
    assert [l for l, _ in plan.no_well_rows] == [5]
    assert any("1 row(s) excluded" in n for n in w1.notes)


def test_no_well_column_raises(tmp_path):
    options = ImportOptions(kind="tops")
    path = write(tmp_path, "Formation,Top (ft)\nA,100\n")
    parsed = parse_import_file(path, options)
    with pytest.raises(ValueError, match="no well column"):
        build_import_plan(parsed, path, [], options)


# ---------------------------------------------------------------------------
# Records and column override
# ---------------------------------------------------------------------------
def test_import_record_keys(tmp_path):
    path = write(tmp_path, TOPS)
    plan = plan_for(path, [ref("BKS-01")])
    rec = import_record(plan, plan.rows[0])
    assert set(rec) == {"path", "file_well", "spellings", "columns", "delimiter", "decimal",
                        "encoding", "sheet", "depth_unit", "fill_down", "last_bottom"}
    assert rec["path"] == path and rec["file_well"] == "BKS-01"
    assert rec["spellings"] == ["BKS-01", "bks 01"]
    assert rec["columns"] == {"well": "Well", "name": "Formation",
                              "top": "Top (ft)", "bottom": "Bottom (ft)"}
    assert (rec["delimiter"], rec["decimal"], rec["depth_unit"]) == (",", ".", "FT")
    assert rec["fill_down"] is False and rec["last_bottom"] == "log_bottom"
    assert rec["sheet"] is None


def test_columns_override_round_trips_through_record(tmp_path):
    text = "Well,Formation,Top,Pick MD\nW1,A,5,100\nW1,B,6,200\n"
    path = write(tmp_path, text)
    wells = [ref("W1")]
    default = plan_for(path, wells, depth_unit="FT")
    assert default.rows[0].part.formations[0].top_depth == 5.0

    plan = plan_for(path, wells, depth_unit="FT",
                    columns={"top": "pick md", "bottom": None})
    assert plan.rows[0].part.formations[0].top_depth == 100.0
    assert plan.parsed.columns_detected == {
        "well": "Well", "name": "Formation", "top": "Pick MD", "bottom": None}
    rec = import_record(plan, plan.rows[0])
    assert rec["columns"]["top"] == "Pick MD"

    replay = plan_for(path, wells, depth_unit=rec["depth_unit"], columns=rec["columns"])
    assert replay.rows[0].part.formations[1].top_depth == 200.0
    assert import_record(replay, replay.rows[0])["columns"] == rec["columns"]


def test_columns_override_unknown_header_fails_clearly(tmp_path):
    path = write(tmp_path, TOPS)
    with pytest.raises(ValueError, match="Nope"):
        parse_import_file(path, ImportOptions(kind="tops", columns={"top": "Nope"}))


def test_columns_override_core(tmp_path):
    text = "Well,Depth (ft),Phi A,Phi B\nW1,1000,0.1,0.3\n"
    path = write(tmp_path, text)
    plan = plan_for(path, [ref("W1")], kind="core", columns={"porosity": "PHI B"})
    part = plan.rows[0].part
    assert part.data[part.porosity_col].iloc[0] == pytest.approx(0.3)
    assert plan.parsed.columns_detected == {
        "well": "Well", "depth": "Depth (ft)", "porosity": "Phi B",
        "permeability": None, "grain_density": None}


def test_build_parts_skips_keep_and_skip(tmp_path):
    path = write(tmp_path, "Well,Formation,Top (ft)\nA,X,10\nB,X,10\nC,X,10\n")
    wells = [ref("A"), ref("B", existing_count=1), ref("C")]
    plan = plan_for(path, wells)
    plan.set_action(2, "skip")
    assert list(build_parts(plan, wells)) == ["WELL:A"]


# ---------------------------------------------------------------------------
# Project snapshot
# ---------------------------------------------------------------------------
def test_well_refs_from_project(tmp_path):
    from models.project import Project, WellDataset
    from modules.formation_tops import FormationTops

    project = Project()
    ds = WellDataset(key="WELL:BKS-01", display_name="BKS-01")
    ds.identity = {"well_name": "BKS-01", "uwi": "100/01"}
    ds.las_data = pd.DataFrame({"DEPTH": [1000.0, 1500.0, 2000.0], "GR": [1.0, 2.0, 3.0]})
    tops = FormationTops()
    assert tops.read_tops_from_buffer(__import__("io").StringIO(TOPS.strip()))
    ds.formation_tops = tops
    ds.tops_path = "C:/data/tops.csv"
    ds.selected_formations = ["A"]
    ds.zone_overrides = {"Alpha": {"phi": {"mode": "manual", "value": 0.1}}}
    empty = WellDataset(key="WELL:EMPTY", display_name="EMPTY")
    project.add_well(ds)
    project.add_well(empty, activate=False)
    project.zone_params = {"beta": {"a": {"mode": "manual", "value": 1.0}}, "gamma": {}}

    refs = well_refs(project)
    assert [r.key for r in refs] == ["WELL:BKS-01", "WELL:EMPTY"]
    first = refs[0]
    assert (first.log_top, first.log_bottom) == (1000.0, 2000.0)
    assert first.well_info["uwi"] == "100/01"
    assert first.existing_count == 4 and first.existing_path == "C:/data/tops.csv"
    assert first.zones_with_params == ["BETA", "ALPHA"]
    assert first.selected_formations == ["A"]
    assert refs[1].log_top is None and refs[1].existing_count == 0
    assert well_refs(project, "core")[0].existing_count == 0
