"""Global-volume ramps for every BGM transition (FR-013, FR-016, D-003, D-013).

Volume is *written* only through Kodi's ``SetVolume`` builtin, always without
its optional ``showVolumeBar`` argument, because JSON-RPC's
``Application.SetVolume`` pops the volume OSD unconditionally (D-013). Volume
is *read* through JSON-RPC ``Application.GetProperties``, which has no such
side effect.

A ramp runs on a daemon thread (constitution 2.1) so a Kodi callback thread is
never blocked for a full second; at most one ramp is ever *authoritative*, and
a new ``fade`` supersedes the previous one. The single exception to "off the
calling thread" is ``IN``'s snap to silence, which runs inline: at a clip's
start it is racing the clip's audio becoming audible, and thread-startup
latency loses that race (risk R-6).

Who may write is decided by a *generation counter*, not by whether a
cancellation Event is set. Every transition -- a ``fade``, a :func:`cancel`, a
:func:`restore` -- claims a new generation under ``_lock``, and a ramp
re-checks its own generation *inside the same critical section as its write*.
A worker that cleared its cancellation check and only then lost its scheduling
slice therefore either writes before the transition or never writes at all: it
can no longer land a mid-ramp value *after* teardown restored the user's
volume, which is the one failure with a lasting user-visible consequence
(D-003). Checking outside the lock would leave exactly that gap open. The
Event is kept purely as a latency optimization -- it wakes a sleeping outgoing
worker instead of letting it sleep out its step interval -- and is never the
correctness mechanism.

Holding ``_lock`` across a Kodi ``executebuiltin`` call is a deliberate
trade-off: the lock covers a single volume write, never a whole ramp, so
:func:`effective_baseline` -- called from Kodi's callback thread at a clip's
start, the R-6-sensitive path -- waits at most one such call. The JSON-RPC
read in :func:`capture_baseline` is the one thing never held under it.

This module deliberately imports nothing from the addon -- not even
``messages`` -- per contracts/modules.md's dependency graph.
"""

import enum
import json
import threading
import time
from typing import List, Optional, Tuple

import xbmc

MIN_VOLUME = 0
MAX_VOLUME = 100
STEP_COUNT = 20

_lock = threading.Lock()
_generation = 0
_worker: Optional[threading.Thread] = None
_workers: List[threading.Thread] = []
_cancelled = threading.Event()
_target: Optional[int] = None


class Direction(enum.Enum):
    """Which way a ramp runs.

    Attributes:
        IN: Silence up to the baseline.
        OUT: The current volume down to silence.
    """

    IN = "in"
    OUT = "out"


def _clamp(percent: int) -> int:
    """Force a percentage into Kodi's 0-100 volume range.

    Args:
        percent: Possibly out-of-range volume percentage.

    Returns:
        The percentage clamped to 0-100.
    """
    return max(MIN_VOLUME, min(MAX_VOLUME, percent))


def _set_volume(percent: int) -> None:
    """Write the global volume via the builtin, leaving the OSD alone (D-013).

    Args:
        percent: Volume percentage, already clamped.
    """
    xbmc.executebuiltin("SetVolume({0})".format(percent))


def capture_baseline() -> int:
    """Read the current global volume over JSON-RPC.

    Called at session start, and again at each PLAYING -> SUSPENDED transition
    and before an end-of-session fade-out, so the value always reflects the
    volume last observed while BGM was audible (FR-016).

    Returns:
        The current volume, 0-100. Falls back to 100 -- Kodi's own default --
        when the read is rejected or malformed, since this module has no
        logging dependency and must still return a usable target.
    """
    response = xbmc.executeJSONRPC(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "Application.GetProperties",
                "params": {"properties": ["volume"]},
            }
        )
    )
    try:
        volume = json.loads(response)["result"]["volume"]
        return _clamp(int(volume))
    except (KeyError, TypeError, ValueError):
        return MAX_VOLUME


def _claim(target: Optional[int]) -> Tuple[int, threading.Event]:
    """Start a new generation, invalidating every ramp already in flight.

    The caller MUST hold :data:`_lock`: claiming a generation and making the
    state change it authorizes have to be one atomic step, or two concurrent
    transitions interleave and the older one wins.

    Setting the outgoing cancellation Event here is a latency optimization
    only -- it saves a sleeping worker the rest of its step interval. What
    makes an abandoned ramp *harmless* is the generation it can no longer
    match.

    Args:
        target: Volume the incoming transition heads for, or None when it
            leaves no ramp behind (:func:`cancel`, :func:`restore`).

    Returns:
        The new generation, and the Event an incoming ramp waits on.
    """
    global _generation, _cancelled, _target, _worker
    _generation += 1
    _cancelled.set()
    _cancelled = threading.Event()
    _target = target
    _worker = None
    # Every fade retires a worker and a slideshow runs many fades, so drop the
    # ones that have finished while the lock is already held for the new one.
    _workers[:] = [thread for thread in _workers if thread.is_alive()]
    return _generation, _cancelled


def _write_if_current(generation: int, percent: int) -> bool:
    """Write ``percent`` only while ``generation`` is still the live one.

    The check and the write share one critical section on purpose: checking
    outside it would reopen the window where a superseded worker's write lands
    after the transition that superseded it.

    Args:
        generation: The generation the caller was started for.
        percent: Volume percentage, already clamped.

    Returns:
        True when the write happened, False when a newer transition has
        already claimed a generation and nothing was written.
    """
    with _lock:
        if generation != _generation:
            return False
        _set_volume(percent)
        return True


def _ramp(
    start: int,
    end: int,
    duration_ms: int,
    generation: int,
    cancelled: threading.Event,
) -> None:
    """Step the volume from ``start`` to ``end``, stopping early if superseded.

    Args:
        start: Volume the ramp begins at, already clamped.
        end: Volume the ramp finishes on, already clamped.
        duration_ms: Total ramp time in milliseconds.
        generation: The generation this ramp was started for; every step is
            written only while it is still the live one.
        cancelled: Set when this ramp is superseded, so a sleeping step wakes
            at once instead of sleeping out its interval.
    """
    steps = max(1, min(STEP_COUNT, abs(end - start)))
    interval = duration_ms / steps / 1000.0
    for step in range(1, steps + 1):
        if cancelled.wait(interval):
            return
        volume = start + int(round((end - start) * step / steps))
        if not _write_if_current(generation, volume):
            return


def fade(direction: Direction, baseline: int, duration_ms: int = 1000) -> None:
    """Ramp the global volume, returning before the ramp completes.

    ``IN`` snaps to silence synchronously on the calling thread and then ramps
    up to ``baseline``; ``OUT`` ramps from the current volume down to silence.
    One call claims exactly one generation, so any ramp already in flight is
    superseded as an indivisible part of starting this one.

    Args:
        direction: :data:`Direction.IN` or :data:`Direction.OUT`.
        baseline: Volume the fade-in targets, 0-100 (clamped).
        duration_ms: Ramp duration in milliseconds.
    """
    if direction is Direction.IN:
        _fade_in(_clamp(baseline), duration_ms)
    else:
        _fade_out(duration_ms)


def _fade_in(target: int, duration_ms: int) -> None:
    """Snap to silence, then ramp up to ``target``.

    The snap stays inline on the calling thread -- at a clip's start it is
    racing the clip's audio becoming audible and thread-startup latency loses
    that race (R-6) -- but it is written inside the same critical section that
    claims the generation, so a concurrent transition can no longer land
    between the snap and the ramp it belongs to.

    Args:
        target: Volume the ramp finishes on, already clamped.
        duration_ms: Ramp duration in milliseconds.
    """
    with _lock:
        generation, cancelled = _claim(target)
        _set_volume(MIN_VOLUME)
        _start_worker(MIN_VOLUME, target, duration_ms, generation, cancelled)


def _fade_out(duration_ms: int) -> None:
    """Ramp the current volume down to silence.

    :func:`capture_baseline` is a JSON-RPC round trip, so it runs outside the
    lock -- but a slow read must not let a stale baseline overwrite a newer
    transition, so the generation is re-checked before the value is used and
    the whole transition abandoned when a newer one has been claimed
    meanwhile (otherwise a baseline sampled before a newer fade-in's snap
    would ramp down from a volume nobody is at any more).

    Args:
        duration_ms: Ramp duration in milliseconds.
    """
    with _lock:
        generation, cancelled = _claim(MIN_VOLUME)
    start = capture_baseline()
    with _lock:
        if generation != _generation:
            return
        _start_worker(start, MIN_VOLUME, duration_ms, generation, cancelled)


def _start_worker(
    start: int,
    end: int,
    duration_ms: int,
    generation: int,
    cancelled: threading.Event,
) -> None:
    """Run one ramp on a fresh daemon thread (constitution 2.1).

    The caller MUST hold :data:`_lock`: the worker has to become joinable in
    the same critical section that claimed its generation, or :func:`join`
    could snapshot the thread list without it.

    Args:
        start: Volume the ramp begins at.
        end: Volume the ramp finishes on.
        duration_ms: Ramp duration in milliseconds.
        generation: The generation this ramp writes under.
        cancelled: The Event that wakes this ramp when it is superseded.
    """
    global _worker
    _worker = threading.Thread(
        target=_ramp,
        args=(start, end, duration_ms, generation, cancelled),
        name="slideshow-bgm-fade",
        daemon=True,
    )
    _workers.append(_worker)
    _worker.start()


def effective_baseline() -> int:
    """The volume level to treat as "baseline" right now (FR-016, D-012).

    A plain :func:`capture_baseline` reads whatever Kodi reports at this
    instant -- while a ramp is in flight that is a transient mid-step value,
    not a level anyone actually settled on. Re-baselining onto that value
    (at a clip's start, or a teardown that races an in-progress fade-in)
    would corrupt the very invariant FR-016 exists to protect. While a ramp
    is running, this returns the volume it is heading *to* instead; with
    none running, it is exactly :func:`capture_baseline`.

    Returns:
        The ramp's target when one is in flight, else the current volume.
    """
    with _lock:
        worker = _worker
        target = _target
    if worker is not None and worker.is_alive() and target is not None:
        return target
    return capture_baseline()


def restore(baseline: int) -> None:
    """Set the volume back to ``baseline``. Idempotent, never raises (D-003).

    Runs in a ``finally`` on every exit path, so it swallows its own errors
    rather than masking whatever exception is already unwinding.

    Claiming a new generation and writing the volume in the same critical
    section is what makes this the last word: a ramp step already past its
    cancellation check can no longer land afterwards, so teardown racing a
    fade-in cannot leave the user's volume attenuated. Callers therefore do
    not have to :func:`cancel` first.

    Args:
        baseline: Volume to restore, 0-100 (clamped).
    """
    percent = _clamp(baseline)
    try:
        with _lock:
            _claim(None)
            _set_volume(percent)
    except Exception:  # noqa: BLE001 - last thing to run; must not raise
        pass


def cancel() -> None:
    """Abandon any ramp in flight without waiting for it to unwind.

    A thin caller of the same transition every ``fade`` makes: it claims a
    generation the abandoned ramp can no longer match, so a step already past
    its cancellation check writes nothing once this returns.
    """
    with _lock:
        _claim(None)


def join(timeout: Optional[float] = None) -> bool:
    """Wait for the ramps in flight to finish.

    Used by session teardown to join the fade threads with a timeout, so a
    hung ramp cannot keep the process alive (FR-004). Every worker is waited
    on, not just the newest: a superseded ramp is still a live thread until it
    notices, and constitution 2.1 lets none of them outlive the script.

    ``_lock`` is held only long enough to snapshot that list -- never across a
    join, which would deadlock against the worker's own final generation check
    -- and ``timeout`` is one overall budget rather than a fresh allowance per
    thread, which for N threads could wait N times as long.

    Args:
        timeout: Seconds to wait in total; ``None`` waits indefinitely.

    Returns:
        True when no ramp is still running once the wait is over.
    """
    with _lock:
        workers = list(_workers)
    deadline = None if timeout is None else time.monotonic() + timeout
    for worker in workers:
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        worker.join(remaining)
    return not any(worker.is_alive() for worker in workers)
