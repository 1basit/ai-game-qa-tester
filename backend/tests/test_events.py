import pytest

from gameqa.core import EventAccumulator, PersistenceRule

DT = 1 / 12  # 12 FPS sampled stream


def feed(acc, pattern, scores=None):
    """pattern: string of '1'/'0' per sampled frame."""
    events = []
    for i, ch in enumerate(pattern):
        score = scores[i] if scores else 1.0
        events += acc.update(frame_index=i * 5, timestamp_s=i * DT, active=ch == "1", score=score)
    return events + acc.flush()


def test_single_frame_noise_is_suppressed():
    acc = EventAccumulator(PersistenceRule(min_frames=2))
    assert feed(acc, "0001000100") == []


def test_persistent_event_is_reported_with_bounds():
    acc = EventAccumulator(PersistenceRule(min_frames=3))
    (ev,) = feed(acc, "0011110000")
    assert (ev.start_frame, ev.end_frame) == (10, 25)
    assert ev.start_time_s == pytest.approx(2 * DT)
    assert ev.end_time_s == pytest.approx(5 * DT)
    assert ev.n_active == 4


def test_short_gap_is_bridged_long_gap_splits():
    rule = PersistenceRule(min_frames=2, max_gap_s=0.2)  # tolerates 2 missing frames at 12 FPS
    assert len(feed(EventAccumulator(rule), "11001100000")) == 1
    assert len(feed(EventAccumulator(rule), "110001100000")) == 2


def test_min_duration():
    rule = PersistenceRule(min_frames=1, min_duration_s=0.3)
    assert feed(EventAccumulator(rule), "0111000") == []  # 2 intervals = 0.167 s
    assert len(feed(EventAccumulator(rule), "0111110")) == 1  # 4 intervals = 0.333 s


def test_peak_tracks_highest_score():
    acc = EventAccumulator(PersistenceRule(min_frames=2))
    (ev,) = feed(acc, "0111", scores=[0, 0.2, 0.9, 0.5])
    assert ev.peak_frame == 10 and ev.peak_score == 0.9
    assert ev.mean_score == pytest.approx((0.2 + 0.9 + 0.5) / 3)


def test_event_open_at_end_of_video_is_flushed():
    acc = EventAccumulator(PersistenceRule(min_frames=2))
    assert len(feed(acc, "000111")) == 1


def test_out_of_order_frames_rejected():
    acc = EventAccumulator()
    acc.update(0, 1.0, True)
    with pytest.raises(ValueError, match="timestamp order"):
        acc.update(1, 0.5, True)
