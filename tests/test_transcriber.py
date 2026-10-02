"""The transcriber's pure parts; the model itself is measured by hand (ticket 01)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("worker", Path(__file__).resolve().parent.parent / "asr" / "worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)  # no speech runtime needed: it's imported only when the worker runs


def test_a_long_recording_is_cut_at_its_quietest_moments():
    frame = 1.0  # one energy value per second, for readability
    energy = [1.0] * 100
    energy[23] = energy[38] = energy[61] = 0.0  # pauses
    cuts = worker.quiet_cuts(energy, frame=frame, window=20, spread=5)
    # each cut at a pause near 20 s of speech; 39 s with no pause after the last one still gets a cut
    assert cuts == [23, 38, 61, 76]
    assert all(b - a <= 25 for a, b in zip([0] + cuts, cuts + [100]))


def test_a_short_recording_is_one_piece():
    assert worker.quiet_cuts([1.0] * 20, frame=1.0, window=20, spread=5) == []
