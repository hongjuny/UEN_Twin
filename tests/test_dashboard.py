import sys
from pathlib import Path

import pytest

from uetn_twin import engine, topology

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"
sys.path.insert(0, str(DASHBOARD))

import map_view  # noqa: E402
import panels  # noqa: E402


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    topo = topology.load()
    out = tmp_path_factory.mktemp("outputs")
    engine.write_run(topo, engine.run_simulation(topo, 24), out)
    return out


def test_dashboard_first_render_has_no_exception(run_dir, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("UETN_OUT_DIR", str(run_dir))
    at = AppTest.from_file(str(DASHBOARD / "app.py"), default_timeout=120).run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert labels == ["Total traffic", "Max link utilization", "Links above 80%", "Unreachable sites"]
    assert at.select_slider[0].value.hour == 10  # default view is weekday 10:00


def test_time_changes_traffic(run_dir, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("UETN_OUT_DIR", str(run_dir))
    day = AppTest.from_file(str(DASHBOARD / "app.py"), default_timeout=120).run()
    night_app = AppTest.from_file(str(DASHBOARD / "app.py"), default_timeout=120)
    night_app.query_params["t"] = "02:00"
    night = night_app.run()
    assert not night.exception
    assert night.select_slider[0].value.hour == 2
    assert float(night.metric[0].value.split()[0]) < 0.3 * float(day.metric[0].value.split()[0])


def test_kpis_and_top_links_table(run_dir):
    import pandas as pd

    topo = topology.load()
    df = pd.read_parquet(next(Path(run_dir).glob("run_*/snapshots.parquet")))
    df_t = df[df.t == df.t.iloc[0]]
    k = panels.kpi_values(df_t)
    assert k["unreachable_sites"] == 0 and 0 <= k["max_util"] <= 1
    frame = panels.top_links_frame(df_t, topo, n=5)
    assert set(frame.Source) <= {"map", "inferred", "assumed"}
    assert frame.Util.is_monotonic_decreasing and frame.Util.dtype.kind == "i"


def test_map_uses_discrete_bands_and_hides_unselected_layers():
    topo = topology.load()
    assert [map_view.util_band(u) for u in (0.0, 0.59, 0.6, 0.84, 0.85, 0.99, 1.0, 1.4)] == [0, 0, 1, 1, 2, 2, 3, 3]
    state = {ln.id: dict(up=True, load_gbps=1.0, utilization=0.5) for ln in topo.links}
    all_fig = map_view.build_map(topo, state, {}, {})
    core_fig = map_view.build_map(topo, state, {}, {}, tier_mode="core")
    assert len(core_fig.data) <= len(all_fig.data)
    assert all_fig.layout.height == map_view.MAP_HEIGHT and all_fig.layout.width == map_view.MAP_WIDTH


def test_labels_legend_and_display_text(run_dir, monkeypatch):
    from streamlit.testing.v1 import AppTest

    topo = topology.load()
    state = {ln.id: dict(up=True, load_gbps=1.0, utilization=0.5) for ln in topo.links}
    with_labels = map_view.build_map(topo, state, {}, {}, show_labels=True)
    without = map_view.build_map(topo, state, {}, {}, show_labels=False)
    text_traces = [t for t in with_labels.data if t.mode == "text"]
    assert len(text_traces) == 1 and not [t for t in without.data if t.mode == "text"]
    labels = {x.replace("<b>", "").replace("</b>", "") for x in text_traces[0].text}
    assert {"USU", "WSU", "SLC", "UVU", "Moab", "Price", "Wendover"} <= labels
    assert list(text_traces[0].text).count("<b>SLC</b>") == 1  # one label for the 4 Salt Lake PoPs
    assert "core, inferred" in with_labels.layout.annotations[0].text

    monkeypatch.setenv("UETN_OUT_DIR", str(run_dir))
    at = AppTest.from_file(str(DASHBOARD / "app.py"), default_timeout=120).run()
    assert not at.exception
    assert at.radio[0].options == ["core", "core+distribution"]  # no external option in v0
    shown = " ".join(c.value for c in at.caption)
    assert "Simulated weekday (semester), 10:00" in shown and "2026" not in shown
    assert at.select_slider[0].options[0] == "00:00"
