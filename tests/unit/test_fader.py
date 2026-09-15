"""Tests for resources/lib/fader.py (FR-013, FR-016, D-003, D-013, risk R-6)."""

import json
import threading
import time
from typing import Any, Dict, Iterator, List, Set

import pytest
import xbmc

from resources.lib import fader
from resources.lib.fader import Direction

world = xbmc.world

SHORT_MS = 50
LONG_MS = 5000
# Safety valve only: a parked thread must never be able to hang the suite.
STALL_TIMEOUT = 10.0
# The name fader.py gives its ramp threads; the only way to observe from
# outside that none of them outlived a join (constitution 2.1).
RAMP_THREAD_NAME = "slideshow-bgm-fade"


@pytest.fixture(autouse=True)
def _stop_ramps_between_tests() -> Iterator[None]:
    """Never let a ramp from one test bleed volume calls into the next."""
    yield
    fader.cancel()
    fader.join(2.0)


def _spy_on_jsonrpc(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    """Record every JSON-RPC request while still serving real fake responses."""
    requests: List[Dict[str, Any]] = []
    original = xbmc.executeJSONRPC

    def spy(request: str) -> str:
        requests.append(json.loads(request))
        response: str = original(request)
        return response

    monkeypatch.setattr(xbmc, "executeJSONRPC", spy)
    return requests


def _volumes() -> List[int]:
    return [percent for percent, _ in world.volume_calls]


class _Stall:
    """Parks ramp threads at a chosen point and holds them until released.

    The calling (main) thread is never parked, so a test can drive a competing
    transition while a ramp sits in the window under test.
    """

    def __init__(self, park: int = 1) -> None:
        self._limit = park
        self._condition = threading.Condition()
        self._parked: Set[int] = set()
        self._released = threading.Event()

    def park(self) -> None:
        """Hold the calling worker thread here until :meth:`release`.

        Only the first ``park`` threads are held; later arrivals pass straight
        through, so a test can hold one ramp while another runs to completion.
        """
        if threading.current_thread() is threading.main_thread():
            return
        ident = threading.get_ident()
        with self._condition:
            if ident in self._parked or len(self._parked) >= self._limit:
                return
            self._parked.add(ident)
            self._condition.notify_all()
        self._released.wait(STALL_TIMEOUT)

    def wait_until_parked(self, count: int = 1) -> bool:
        """Block until at least ``count`` workers are parked."""
        with self._condition:
            return self._condition.wait_for(
                lambda: len(self._parked) >= count, STALL_TIMEOUT
            )

    def release(self) -> None:
        """Let every parked worker continue."""
        self._released.set()


def _park_ramp_writes(monkeypatch: pytest.MonkeyPatch, stall: _Stall) -> None:
    """Park ramp threads at the instant they are about to write a volume.

    Substituted for *both* ``fader._lock`` and ``fader._set_volume``, so a ramp
    parks at whichever it reaches first: the critical section that guards a
    volume write, or -- if a write is attempted without one -- the write
    itself. Either way the worker is held in the exact window a superseding
    transition has to survive: after its cancellation check has cleared, and
    before its write has landed. Parking at the lock happens *before* it is
    acquired, so the parked worker blocks nobody.
    """
    real_lock = fader._lock
    real_set_volume = fader._set_volume

    class _GatedLock:
        def __enter__(self) -> None:
            stall.park()
            real_lock.acquire()

        def __exit__(self, *exc_info: object) -> None:
            real_lock.release()

    def gated_set_volume(percent: int) -> None:
        stall.park()
        real_set_volume(percent)

    monkeypatch.setattr(fader, "_lock", _GatedLock())
    monkeypatch.setattr(fader, "_set_volume", gated_set_volume)


def _park_baseline_reads(monkeypatch: pytest.MonkeyPatch, stall: _Stall) -> None:
    """Park a worker thread inside the JSON-RPC volume read, after it answers.

    ``capture_baseline`` is a round trip to Kodi, so it must run outside the
    lock; holding a fade-out in there -- with the pre-snap volume already in
    hand -- while a newer fade-in claims the volume is only possible if the
    lock really is released across the read.
    """
    real_execute = xbmc.executeJSONRPC

    def parked(request: str) -> str:
        response: str = real_execute(request)
        stall.park()
        return response

    monkeypatch.setattr(xbmc, "executeJSONRPC", parked)


def _live_ramp_threads() -> List[threading.Thread]:
    """Every ramp thread still running -- none may outlive a join (2.1)."""
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == RAMP_THREAD_NAME and thread.is_alive()
    ]


def _join_ramp_threads(timeout: float = 5.0) -> None:
    """Join every live ramp thread, so no test leaks one into the next."""
    deadline = time.monotonic() + timeout
    for thread in threading.enumerate():
        if thread.name == RAMP_THREAD_NAME:
            thread.join(max(0.0, deadline - time.monotonic()))


def test_capture_baseline_reports_the_current_volume() -> None:
    world.volume = 37

    assert fader.capture_baseline() == 37


def test_capture_baseline_reads_volume_over_json_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _spy_on_jsonrpc(monkeypatch)
    world.volume = 42

    fader.capture_baseline()

    assert [request["method"] for request in requests] == ["Application.GetProperties"]
    assert "volume" in requests[0]["params"]["properties"]


def test_capture_baseline_falls_back_to_full_volume_when_the_read_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        xbmc,
        "executeJSONRPC",
        lambda request: json.dumps(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "nope"}}
        ),
    )

    assert fader.capture_baseline() == 100


def test_fade_in_snaps_to_silence_before_returning() -> None:
    world.volume = 100

    fader.fade(Direction.IN, 100, duration_ms=LONG_MS)

    # Asserted without joining: the snap must not wait on thread startup (R-6).
    assert world.volume_calls[0] == (0, False)


def test_fade_in_ramps_from_silence_up_to_the_baseline() -> None:
    fader.fade(Direction.IN, 80, duration_ms=SHORT_MS)
    assert fader.join(2.0) is True

    assert _volumes()[0] == 0
    assert _volumes()[-1] == 80
    assert len(_volumes()) > 2
    assert _volumes() == sorted(_volumes())


def test_fade_out_ramps_down_to_silence_from_the_current_volume() -> None:
    world.volume = 80

    fader.fade(Direction.OUT, 80, duration_ms=SHORT_MS)
    assert fader.join(2.0) is True

    assert _volumes()[-1] == 0
    assert len(_volumes()) > 2
    assert _volumes() == sorted(_volumes(), reverse=True)


def test_fade_out_does_not_snap_to_silence_first() -> None:
    world.volume = 80

    fader.fade(Direction.OUT, 80, duration_ms=LONG_MS)

    # Unlike IN, OUT has no inline snap: nothing is written before the ramp.
    assert world.volume_calls == []
    assert world.volume == 80


def test_no_fade_step_ever_asks_kodi_to_show_the_volume_bar() -> None:
    world.volume = 60

    fader.fade(Direction.IN, 60, duration_ms=SHORT_MS)
    fader.join(2.0)
    fader.fade(Direction.OUT, 60, duration_ms=SHORT_MS)
    fader.join(2.0)
    fader.restore(60)

    assert len(world.volume_calls) > 4
    assert [shown for _, shown in world.volume_calls] == [False] * len(
        world.volume_calls
    )


def test_volume_is_never_written_over_json_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _spy_on_jsonrpc(monkeypatch)

    fader.fade(Direction.IN, 50, duration_ms=SHORT_MS)
    fader.join(2.0)
    fader.fade(Direction.OUT, 50, duration_ms=SHORT_MS)
    fader.join(2.0)
    fader.restore(50)

    assert {request["method"] for request in requests} <= {"Application.GetProperties"}


def test_fade_in_to_a_silent_baseline_stays_silent() -> None:
    fader.fade(Direction.IN, 0, duration_ms=SHORT_MS)
    assert fader.join(2.0) is True

    assert _volumes()[-1] == 0


def test_fade_clamps_a_baseline_above_the_kodi_maximum() -> None:
    fader.fade(Direction.IN, 150, duration_ms=SHORT_MS)
    assert fader.join(2.0) is True

    assert _volumes()[-1] == 100


def test_a_new_fade_supersedes_the_one_in_flight() -> None:
    world.volume = 100

    fader.fade(Direction.IN, 100, duration_ms=200)
    fader.fade(Direction.OUT, 100, duration_ms=SHORT_MS)
    assert fader.join(2.0) is True
    settled = list(world.volume_calls)

    # Longer than the superseded ramp: a ramp still running would write again.
    threading.Event().wait(0.3)

    assert world.volume_calls == settled
    assert world.volume == 0


def test_cancel_abandons_the_ramp_in_flight() -> None:
    fader.fade(Direction.IN, 100, duration_ms=LONG_MS)

    fader.cancel()

    # A 5 s ramp that finishes inside 1 s can only have been cut short.
    assert fader.join(1.0) is True
    assert world.volume < 100
    assert _volumes()[-1] < 100


def test_cancel_is_safe_when_no_fade_is_running() -> None:
    fader.cancel()

    assert world.volume_calls == []


def test_restore_sets_the_volume_back_in_one_call() -> None:
    world.volume = 0

    fader.restore(65)

    assert world.volume_calls == [(65, False)]
    assert world.volume == 65


def test_restore_clamps_a_volume_above_the_kodi_maximum() -> None:
    world.volume = 50

    fader.restore(140)

    assert world.volume_calls == [(100, False)]


def test_restore_clamps_a_negative_volume() -> None:
    fader.restore(-20)

    assert world.volume == 0


def test_restore_is_idempotent() -> None:
    fader.restore(55)
    fader.restore(55)

    assert world.volume_calls == [(55, False), (55, False)]
    assert world.volume == 55


def test_restore_swallows_a_kodi_failure_so_it_cannot_mask_a_teardown_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(function: str) -> None:
        raise RuntimeError("Kodi is shutting down")

    monkeypatch.setattr(xbmc, "executebuiltin", boom)

    fader.restore(50)


def test_effective_baseline_returns_the_ramp_target_while_fading_in() -> None:
    # A fresh JSON-RPC read mid-ramp would catch whatever partial volume the
    # last step wrote -- not a level anyone (the user, or a prior fade)
    # actually settled on. FR-016/D-012 want the level BGM is heading *to*.
    world.volume = 0

    fader.fade(Direction.IN, 80, duration_ms=LONG_MS)

    assert fader.effective_baseline() == 80
    assert fader.capture_baseline() != 80  # the naive read is caught mid-ramp


def test_effective_baseline_matches_capture_baseline_when_idle() -> None:
    world.volume = 44

    assert fader.effective_baseline() == fader.capture_baseline() == 44


def test_effective_baseline_reads_fresh_once_a_ramp_has_finished() -> None:
    world.volume = 10

    fader.fade(Direction.IN, 30, duration_ms=SHORT_MS)
    assert fader.join(2.0) is True

    assert fader.effective_baseline() == 30


def test_restore_wins_over_a_ramp_that_was_cancelled_first() -> None:
    world.volume = 70

    fader.fade(Direction.OUT, 70, duration_ms=LONG_MS)
    fader.cancel()
    fader.join(1.0)
    fader.restore(70)

    assert world.volume == 70
    assert world.volume_calls[-1] == (70, False)


def test_a_ramp_step_stalled_at_its_write_never_lands_after_a_newer_fade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A worker can clear its cancellation check and only then lose its
    # scheduling slice. Whatever it was about to write must not overwrite a
    # transition that happened while it was away.
    world.volume = 100
    stale_step = 5  # fade IN 0 -> 100 over 20 steps: step one writes 5
    stall = _Stall()
    _park_ramp_writes(monkeypatch, stall)

    try:
        fader.fade(Direction.IN, 100, duration_ms=SHORT_MS)
        assert stall.wait_until_parked() is True
        fader.fade(Direction.OUT, 100, duration_ms=SHORT_MS)
    finally:
        stall.release()
        joined = fader.join(2.0)
        _join_ramp_threads()

    assert joined is True
    assert stale_step not in _volumes()
    assert world.volume == 0


def test_restore_alone_is_the_last_word_over_a_ramp_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No cancel() first: restore must not carry a hidden ordering
    # precondition, or an exit path that forgets it leaves the user's global
    # volume permanently at a mid-ramp value (D-003).
    world.volume = 70
    stall = _Stall()
    _park_ramp_writes(monkeypatch, stall)

    try:
        fader.fade(Direction.IN, 70, duration_ms=SHORT_MS)
        assert stall.wait_until_parked() is True
        fader.restore(70)
        settled = list(world.volume_calls)
    finally:
        stall.release()
        joined = fader.join(2.0)
        _join_ramp_threads()

    assert joined is True
    assert world.volume_calls == settled
    assert settled[-1] == (70, False)
    assert world.volume == 70


def test_no_volume_write_lands_after_teardown_restores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # session.py's _finish does exactly this: cancel(), then restore(). Exiting
    # a slideshow while a clip's fade-in runs reaches it with a live ramp, and
    # a step that slips through leaves the user's volume permanently wrong.
    world.volume = 70
    stall = _Stall()
    _park_ramp_writes(monkeypatch, stall)

    try:
        fader.fade(Direction.IN, 70, duration_ms=SHORT_MS)
        assert stall.wait_until_parked() is True
        fader.cancel()
        fader.restore(70)
        settled = list(world.volume_calls)
    finally:
        stall.release()
        joined = fader.join(2.0)
        leaked = _live_ramp_threads()
        _join_ramp_threads()

    assert joined is True
    assert leaked == []
    assert world.volume_calls == settled
    assert settled[-1] == (70, False)
    assert world.volume == 70


def test_join_still_waits_for_a_ramp_that_a_newer_fade_retired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The superseded ramp is still a live thread until it notices, and
    # constitution 2.1 lets none of them outlive the script.
    stall = _Stall()
    _park_ramp_writes(monkeypatch, stall)

    try:
        fader.fade(Direction.IN, 100, duration_ms=LONG_MS)
        assert stall.wait_until_parked() is True
        fader.fade(Direction.IN, 40, duration_ms=SHORT_MS)
        joined = fader.join(0.2)
    finally:
        stall.release()
        _join_ramp_threads()

    assert joined is False


def test_join_spends_one_overall_deadline_across_every_ramp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = 0.1
    stall = _Stall(park=5)
    _park_ramp_writes(monkeypatch, stall)

    try:
        # Park each ramp before starting the next, or the newer transition
        # wakes the older one before it ever reaches a write.
        for ramps, target in enumerate((20, 40, 60, 80, 100), start=1):
            fader.fade(Direction.IN, target, duration_ms=SHORT_MS)
            assert stall.wait_until_parked(ramps) is True
        started = time.monotonic()
        joined = fader.join(budget)
        elapsed = time.monotonic() - started
    finally:
        stall.release()
        _join_ramp_threads()

    assert joined is False
    # A fresh allowance per thread would spend five times the budget here.
    assert elapsed < budget * 3


def test_join_does_not_hold_the_lock_a_ramp_needs_to_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A worker needs the same lock for its own final generation check, so a
    # join taken while holding it would deadlock teardown against its ramp.
    stall = _Stall()
    _park_ramp_writes(monkeypatch, stall)
    join_result: List[bool] = []
    joiner = threading.Thread(target=lambda: join_result.append(fader.join(2.0)))

    try:
        fader.fade(Direction.IN, 100, duration_ms=SHORT_MS)
        assert stall.wait_until_parked() is True
        fader.cancel()
        joiner.start()
        stall.release()
        joiner.join(5.0)
        still_joining = joiner.is_alive()
    finally:
        stall.release()
        joiner.join(5.0)
        _join_ramp_threads()

    assert still_joining is False
    assert join_result == [True]


def test_a_fade_out_abandons_a_baseline_a_newer_fade_in_has_overtaken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fade-in's snap to silence is part of its generation, so a fade-out
    # still inside its slow baseline read cannot come back and ramp down from
    # a volume nobody is at any more.
    world.volume = 70
    stall = _Stall()
    _park_baseline_reads(monkeypatch, stall)
    out_fade = threading.Thread(
        target=fader.fade, args=(Direction.OUT, 70, SHORT_MS), name="test-fade-out"
    )

    try:
        out_fade.start()
        assert stall.wait_until_parked() is True
        fader.fade(Direction.IN, 80, duration_ms=SHORT_MS)
    finally:
        stall.release()
        out_fade.join(5.0)
        joined = fader.join(2.0)
        _join_ramp_threads()

    assert out_fade.is_alive() is False
    assert joined is True
    ramp = _volumes()[1:]  # everything after the fade-in's inline snap to 0
    assert ramp == sorted(ramp)  # a stale fade-out interleaves descending steps
    assert ramp[-1] == 80
    assert world.volume == 80


def test_an_overtaken_fade_out_is_not_what_effective_baseline_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # session.py restores the volume effective_baseline() reports, so a
    # fade-out that came back from a slow read and installed itself as the
    # ramp in flight would have teardown restore the user to silence.
    world.volume = 70
    stall = _Stall()
    _park_baseline_reads(monkeypatch, stall)
    out_fade = threading.Thread(
        target=fader.fade, args=(Direction.OUT, 70, LONG_MS), name="test-fade-out"
    )

    try:
        out_fade.start()
        assert stall.wait_until_parked() is True
        fader.fade(Direction.IN, 80, duration_ms=LONG_MS)
    finally:
        stall.release()
        out_fade.join(5.0)

    assert out_fade.is_alive() is False
    assert fader.effective_baseline() == 80
