"""The demo page is built from run files only and carries the banner."""

from __future__ import annotations

from pathlib import Path

from c2r.banner import BANNER
from c2r.viz import dashboard


def test_dashboard_renders_from_run_files(fake_run, tmp_path: Path) -> None:
    out = dashboard.write(fake_run.out, tmp_path / "empty", tmp_path / "demo.html")
    page = out.read_text(encoding="utf-8")
    assert BANNER in page
    assert 'http-equiv="refresh"' in page
    assert "Waiting for the re-plan to start." in page
    after = fake_run.result.metrics_after if hasattr(fake_run.result, "metrics_after") else None
    if after is not None:
        assert (
            f"{after.mean_post_wait:.1f} min" in page or f"{int(after.mean_post_wait)} min" in page
        )


def test_dashboard_tolerates_half_written_ledger(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "ledger.jsonl").write_text('{"actor": "tool", "event": "run_start", "iter', "utf-8")
    page = dashboard.render(tmp_path / "none", run, tmp_path / "demo.html")
    assert "Waiting for the re-plan to start." in page
