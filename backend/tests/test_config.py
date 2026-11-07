import pytest

from gameqa.config import PROJECT_ROOT, load_settings
from gameqa.core import ConfigError


def test_default_config_loads_with_absolute_paths():
    s = load_settings()
    assert s.config_file == PROJECT_ROOT / "config" / "default.yaml"
    assert s.video.allowed_extensions == [".mp4", ".avi", ".mkv"]
    assert 10 <= s.video.analysis_fps <= 15
    assert s.paths.data_dir.is_absolute() and s.paths.data_dir == PROJECT_ROOT / "data"
    assert set(s.enabled_detectors()) == {
        "fps_drop", "texture_pop_in", "animation_glitch", "npc_anomaly", "collision_clipping"
    }


def test_env_overrides_yaml(monkeypatch):
    monkeypatch.setenv("GAMEQA_VIDEO__ANALYSIS_FPS", "15")
    monkeypatch.setenv("GAMEQA_LOGGING__LEVEL", "DEBUG")
    s = load_settings()
    assert s.video.analysis_fps == 15
    assert s.logging.level == "DEBUG"
    assert s.video.max_upload_mb == 2048  # untouched values still come from YAML


def test_keyword_overrides_win(monkeypatch):
    monkeypatch.setenv("GAMEQA_DEVICE", "cpu")
    assert load_settings(device="mps").device == "mps"


def test_per_detector_persistence_override(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "persistence: {min_frames: 3}\n"
        "detectors:\n"
        "  fps_drop: {enabled: true, persistence: {min_frames: 1}}\n"
        "  npc_anomaly: {enabled: false}\n"
    )
    s = load_settings(cfg)
    assert s.persistence_for("fps_drop").min_frames == 1
    assert s.persistence_for("npc_anomaly").min_frames == 3
    assert s.enabled_detectors() == ["fps_drop"]


@pytest.mark.parametrize(
    "yaml_text",
    [
        "video: {analysis_fps: 0}\n",           # out of range
        "evidence: {clip_duration_s: 30}\n",    # FR-4 says 5-10 s
        "unknown_section: 1\n",                 # typos are errors, not silently ignored
    ],
)
def test_invalid_config_raises_config_error(tmp_path, yaml_text):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text(yaml_text)
    with pytest.raises(ConfigError):
        load_settings(cfg)


def test_missing_config_file():
    with pytest.raises(ConfigError, match="not found"):
        load_settings("/nonexistent/config.yaml")
