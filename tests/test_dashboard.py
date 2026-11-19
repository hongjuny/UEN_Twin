import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

from uetn_twin import topology
from uetn_twin.sim.runner import SimRun
from uetn_twin.sim.scenario import load_scenario

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"
sys.path.insert(0, str(DASHBOARD))

import charts  # noqa: E402
import data  # noqa: E402
import map_view  # noqa: E402


def _scenario(hours=2.0):
    return load_scenario("semester_registration_monday").model_copy(update=dict(duration_hours=hours))


@pytest.fixture(scope="module")
def topo():
    return topology.load()


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("outputs")
    SimRun(_scenario(), out_base=out).run()
    return out


def _app(run_dir, monkeypatch, **params):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("UETN_OUT_DIR", str(run_dir))
    app = AppTest.from_file(str(DASHBOARD / "app.py"), default_timeout=120)
    for k, v in params.items():
        app.query_params[k] = v
    return app


def test_first_render_has_badge_kpis_and_no_date(run_dir, monkeypatch):
    at = _app(run_dir, monkeypatch).run()
    assert not at.exception
    assert [m.label for m in at.metric] == ["Total traffic", "Max link utilization", "Links above 80%",
                                            "Dropped traffic"]  # Unreachable sites only when the scenario cuts links
    assert any("SIMULATED" in m.value for m in at.markdown)
    shown = " ".join(c.value for c in at.caption) + " ".join(m.value for m in at.markdown)
    assert "simulated" in shown.lower() and "2026" not in shown and "live data" not in shown.lower()
    assert at.radio[0].options == ["Replay", "Live"] and at.radio[1].options == ["core", "core+distribution"]


def test_time_changes_sessions_and_scenario_panel(run_dir, monkeypatch):
    early = _app(run_dir, monkeypatch, t="06:05").run()
    late = _app(run_dir, monkeypatch, t="07:10").run()
    assert not early.exception and not late.exception
    assert early.select_slider[0].value < late.select_slider[0].value
    panel = lambda a: " ".join(m.value for m in a.markdown)  # noqa: E731
    assert "upcoming" in panel(early) and "active" in panel(late)
    assert "Registration opens at UVU and U of U" in panel(late)


def test_replay_reads_parquet_and_sessions_peak_after_opening(run_dir, topo):
    run = data.RunData(next(Path(run_dir).glob("run_*")))
    assert run.status == "finished" and run.use_parquet
    before = run.node_series("slc-uofu", 0, 600).session_utilization.max()
    after = run.node_series("slc-uofu", 4200, 4800).session_utilization.max()
    assert after > 3 * before
    snap = run.at(data.snap(run.times(), 4200))
    k = data.kpi_values(snap["links"], snap["nodes"], snap["totals"], {})
    assert 0 < k["max_util"] and k["dropped_gbps"] >= 0 and k["unreachable_sites"] == 0
    frame = data.top_links_frame(snap["links"], topo, n=5)
    assert set(frame.Source) <= {"map", "inferred", "assumed"} and frame.Util.is_monotonic_decreasing
    assert frame.Direction.str.contains(" > ").all() and not frame.Direction.str.contains("[A-Z]").any()  # short ids
    assert [o.status for o in data.overlay_infos(run, 4200)] == ["active", "upcoming"]


def test_session_chart_defaults_to_the_overlay_targets(run_dir):
    run = data.RunData(next(Path(run_dir).glob("run_*")))
    assert sorted(data.session_nodes(run)) == ["slc-uofu", "uvu-orem"]  # registration overlay, affects sessions
    base = data.RunData.__new__(data.RunData)
    base.scenario = load_scenario("baseline_weekday")
    assert data.session_nodes(base) == []
    since, until = data.window(4200)
    fig = charts.node_sessions_chart({n: run.node_series(n, since, until) for n in ("uvu-orem", "slc-uofu")}, run.clock)
    assert [t.name for t in fig.data] == ["uvu-orem", "slc-uofu"]


def test_class_colors_are_shared(run_dir):
    from uetn_twin.palette import CLASS_COLORS
    assert charts.CLASS_COLORS is CLASS_COLORS and CLASS_COLORS["general_internet"] == "#59a14f"


def test_link_state_uses_busier_direction_and_down_links(run_dir):
    run = data.RunData(next(Path(run_dir).glob("run_*")))
    links = run.at(run.times()[10])["links"]
    state = data.link_state(links, {"slc-slcc--wendover"})
    assert not state["slc-slcc--wendover"]["up"] and state["uvu-orem--uvu-wasatch"]["up"]
    for s in state.values():
        assert len(s["dirs"]) == 2 and s["utilization"] == max(d["utilization"] for d in s["dirs"])


def test_charts_build(run_dir):
    run = data.RunData(next(Path(run_dir).glob("run_*")))
    since, until = data.window(4200)
    link = "wsu-ogden--slc-ddc"
    f1 = charts.link_direction_chart(run.link_series(link, since, until), run.clock, 100.0, link, 4200)
    assert len(f1.data) == 2 and f1.layout.title.text.startswith(link)
    f2 = charts.class_area_chart(run.class_series(link, "wsu-ogden", since, until), run.clock, "x")
    assert len(f2.data) >= 1
    f3 = charts.node_sessions_chart(run.node_series("slc-uofu", since, until), run.clock, "U of U")
    assert f3.data[0].y.max() > 0


def test_map_uses_discrete_bands_and_session_outline(topo):
    assert [map_view.util_band(u) for u in (0.0, 0.59, 0.6, 0.84, 0.85, 0.99, 1.0, 1.4)] == [0, 0, 1, 1, 2, 2, 3, 3]
    state = {ln.id: dict(up=True, load_gbps=1.0, utilization=0.5,
                         dirs=[dict(frm=ln.a, to=ln.b, gbps=1.0, utilization=0.5, dropped=0.2, latency_ms=3.0),
                               dict(frm=ln.b, to=ln.a, gbps=0.1, utilization=0.05, dropped=0.0, latency_ms=3.0)])
             for ln in topo.links}
    all_fig = map_view.build_map(topo, state, {}, {})
    core_fig = map_view.build_map(topo, state, {}, {}, tier_mode="core")
    assert len(core_fig.data) <= len(all_fig.data)
    assert all_fig.layout.height == map_view.MAP_HEIGHT and all_fig.layout.width == map_view.MAP_WIDTH
    hover = next(t for t in all_fig.data if t.name == "links").text[0]
    assert "rough indicative" in hover and "dropping 0.20" in hover and hover.count(" > ") == 2
    fig = map_view.build_map(topo, state, {}, {}, node_sessions={"slc-uofu": 1.57, "uvu-orem": 0.2})
    core = next(t for t in fig.data if t.name == "core")
    colors = dict(zip(core.customdata, core.marker.line.color))
    assert colors["slc-uofu"] == "#d62728" and colors["uvu-orem"] == "#2e9e5b" and colors["usu-logan"] == "#1f2a44"


def test_labels_legend_and_display_text(topo):
    state = {ln.id: dict(up=True, load_gbps=1.0, utilization=0.5) for ln in topo.links}
    with_labels = map_view.build_map(topo, state, {}, {}, show_labels=True)
    without = map_view.build_map(topo, state, {}, {}, show_labels=False)
    text_traces = [t for t in with_labels.data if t.mode == "text"]
    assert len(text_traces) == 1 and not [t for t in without.data if t.mode == "text"]
    labels = {x.replace("<b>", "").replace("</b>", "") for x in text_traces[0].text}
    assert {"USU", "WSU", "SLC", "UVU", "Moab", "Price", "Wendover"} <= labels
    assert list(text_traces[0].text).count("<b>SLC</b>") == 1  # one label for the 4 Salt Lake PoPs
    assert "core, inferred" in with_labels.layout.annotations[0].text


def test_live_run_is_followed_by_the_dashboard(tmp_path, monkeypatch):
    """Live smoke test: a paced run writes SQLite while AppTest renders Live mode repeatedly without exceptions."""
    scenario = _scenario(hours=3)

    def go():
        SimRun(scenario, speed=1800, out_base=tmp_path).run()  # 3 simulated hours in about 6 s

    th = threading.Thread(target=go)
    th.start()
    try:
        deadline = time.time() + 30
        while time.time() < deadline:  # wait for the first telemetry rows
            dirs = list(tmp_path.glob("run_*"))
            if dirs and (dirs[0] / "telemetry.sqlite").exists():
                with sqlite3.connect(dirs[0] / "telemetry.sqlite") as c:
                    if c.execute("SELECT COUNT(*) FROM totals").fetchone()[0] >= 3:
                        break
            time.sleep(0.2)
        else:
            pytest.fail("no telemetry appeared")
        assert data.read_meta(dirs[0])["status"] == "running"
        assert data.list_runs(tmp_path)[0]["status"] == "running"
        stamps = []
        for _ in range(3):
            app = _app(tmp_path, monkeypatch, mode="live").run()
            assert not app.exception
            assert app.radio[0].value == "Live"
            stamps.append(app.get("progress")[0].proto.text)
            time.sleep(1.0)
        assert stamps[0] != stamps[-1] or "finished" in stamps[-1]  # simulated time moved on between refreshes
    finally:
        th.join(timeout=60)
    meta = data.read_meta(next(tmp_path.glob("run_*")))
    assert meta["status"] == "finished" and meta["finished"]
    done = _app(tmp_path, monkeypatch, mode="live").run()
    assert not done.exception and "finished" in done.get("progress")[0].proto.text
