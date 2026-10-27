"""What she is doing and feeling.

A port of Saber-Theme's ``MascotBrain`` (see tests/test_brain.py). Pure
Python; times are milliseconds from any monotonic clock. The renderer turns
``mood`` (and ``moment``) into a motion and expression and adds the
procedural motion; docs/character.md has the mood -> form -> motion table.
"""

from __future__ import annotations

import random as _random
from collections import deque
from enum import Enum

NEVER = 2**63 - 1


class Mood(Enum):
    IDLE = "idle"
    SURPRISED = "surprised"
    POUT = "pout"
    CRYING = "crying"
    HAPPY = "happy"
    HELD = "held"
    FALLING = "falling"
    SOFT_LANDING = "soft_landing"
    HARD_LANDING = "hard_landing"
    """Dropped while carried flat: she lands flat on her front and gets up (``land(flat=True)``)."""
    DIZZY = "dizzy"
    WALKING = "walking"
    MOMENT = "moment"
    """A short idle animation, see ``Brain.moment``."""
    WANDER = "wander"
    """Strolling to ``Brain.wander_px`` from her spot; ``arrived`` ends it."""
    SLEEPING = "sleeping"
    DANCING = "dancing"
    CURSOR_NEAR = "cursor_near"
    """The cursor is close to her: she reaches for it playfully."""
    CURSOR_FAR = "cursor_far"
    """The cursor is far away: she points at it."""
    TALKING = "talking"
    """Speaking: ``talk`` starts it, ``quiet`` or its time limit ends it."""
    THINKING = "thinking"
    """Agent request: waiting for the LLM."""
    WORKING = "working"
    """Agent request: a tool run (the serious form's analyse)."""
    ALERT = "alert"
    """Agent request: an urgent reminder or mail (the serious form's warn)."""


class Moment(Enum):
    LOOK_AROUND = "look_around"
    STRETCH = "stretch"
    ANALYSE = "analyse"
    SIT = "sit"
    WAVE = "wave"
    CURIOUS = "curious"
    THINKING = "thinking"


POKE_WINDOW_MS = 2_000
POUT_POKES = 3
CRY_POKES = 5
SURPRISE_MS = 900
POUT_MS = 2_200
CRY_MS = 3_000
HAPPY_MS = 2_000
SOFT_LANDING_MS = 600
HARD_LANDING_MS = 2_700  # 3D body: flat impact and a moment lying (1.6 s), then getting up (1.1 s)
HIGH_LANDING_MS = 2_100  # 3D body: Mixamo "Hard Landing" from touchdown (0.6 s in) back to standing
DIZZY_MS = 2_500

# How she lands is decided by the stage (stage.py: drop height, throw speed, wall hits).

SLEEP_AFTER_MS = 60_000
WAKE_TOUCH_MS = 1_000
"""A touch this recent wakes her."""
MOMENT_GAP_MIN_MS = 8_000
MOMENT_GAP_MAX_MS = 20_000
WANDER_CHANCE = 0.25
CURSOR_NEAR_LINGER_MS = 1_400
CURSOR_NEAR_MAX_MS = 2_500
"""How long she reacts to a pointer near her, however long it stays."""
CURSOR_FAR_LINGER_MS = 1_800

CURSOR_MOODS = frozenset({
    Mood.IDLE, Mood.MOMENT, Mood.WANDER, Mood.WALKING, Mood.DANCING, Mood.HAPPY,
    Mood.CURSOR_NEAR, Mood.CURSOR_FAR,
})
"""Moods the cursor interrupts (sulking, held, dazed or busy for the agent she ignores it)."""

AGENT_MOODS = frozenset({Mood.IDLE, Mood.THINKING, Mood.TALKING, Mood.HAPPY, Mood.WORKING, Mood.ALERT})
"""Moods the agent may request; IDLE ends an earlier request."""

REFUSE_REQUESTS = frozenset({Mood.HELD, Mood.FALLING, Mood.DIZZY, Mood.HARD_LANDING})
"""Agent requests wait until she has landed (docs/character.md)."""

_MOMENT_MS = {
    Moment.LOOK_AROUND: 2_600,
    Moment.STRETCH: 1_800,
    Moment.ANALYSE: 2_600,
    Moment.SIT: 6_000,
    Moment.WAVE: 2_200,
    Moment.CURIOUS: 2_000,
    Moment.THINKING: 3_000,
}


def moment_ms(m: Moment) -> int:
    return _MOMENT_MS[m]


class Brain:
    def __init__(self, rng: _random.Random | None = None) -> None:
        self._rng = rng or _random.Random()
        self.mood = Mood.IDLE
        self.moment = Moment.LOOK_AROUND
        self.wander_px = 0.0
        """Wander target from her spot, in px at 96 dpi (the caller scales it)."""
        self.since = 0
        """When the current mood started."""
        self.away_from_home = False
        """Set by the window code: is she away from her spot?"""
        self._until = NEVER
        self._next_moment_at = -1
        self._pokes: deque[int] = deque()
        # tunable from the Customize window (character.py)
        self._near_spent = False  # reacted to the pointer near her; reset when it leaves
        self.performing = False  # playing a pose Kryo picked (perform)
        self.sleep_after_ms = SLEEP_AFTER_MS
        self.moment_gap_ms = (MOMENT_GAP_MIN_MS, MOMENT_GAP_MAX_MS)

    @property
    def busy(self) -> bool:
        return self.mood in (Mood.HELD, Mood.FALLING)

    def poke(self, now: int) -> None:
        if self.busy:
            return
        self._pokes.append(now)
        while self._pokes and now - self._pokes[0] > POKE_WINDOW_MS:
            self._pokes.popleft()
        if len(self._pokes) >= CRY_POKES:
            self._set(Mood.CRYING, now, CRY_MS)
        elif len(self._pokes) >= POUT_POKES:
            self._set(Mood.POUT, now, POUT_MS)
        elif self.mood in (Mood.CRYING, Mood.POUT):
            pass  # keep sulking; more pokes escalate
        else:
            self._set(Mood.SURPRISED, now, SURPRISE_MS)

    def cursor(self, near: bool, now: int) -> None:
        """The cursor is on her monitor (called every frame it stays).

        Near her she reacts once, for CURSOR_NEAR_MAX_MS: a pointer resting beside her
        kept her smiling until a click. She reacts again only after it has left
        (`cursor_left`)."""
        if self.mood not in CURSOR_MOODS or self.performing:  # a picked pose isn't interrupted
            return
        if near:
            if self.mood == Mood.CURSOR_NEAR or self._near_spent:
                return
            self._near_spent = True
            self._set(Mood.CURSOR_NEAR, now, CURSOR_NEAR_MAX_MS)
        elif self.mood != Mood.CURSOR_FAR:
            self._set(Mood.CURSOR_FAR, now, None)
        else:
            self._until = NEVER

    def cursor_left(self) -> None:
        """The cursor moved away from her: the next approach gets a reaction again."""
        self._near_spent = False

    def cursor_near(self, now: int) -> None:
        self.cursor(True, now)

    def cursor_far(self, now: int) -> None:
        self.cursor(False, now)

    def cursor_gone(self, now: int) -> None:
        """The cursor left (or went still): she keeps at it a moment longer."""
        if self.mood == Mood.CURSOR_NEAR:
            self._until = min(self._until, now + CURSOR_NEAR_LINGER_MS)
        elif self.mood == Mood.CURSOR_FAR:
            self._until = now + CURSOR_FAR_LINGER_MS

    def message(self, now: int) -> None:
        """A new chat message: she glances at her bubble, unless busy with something livelier."""
        if self.mood not in (Mood.IDLE, Mood.MOMENT, Mood.WANDER):
            return
        self.moment = Moment.CURIOUS
        self._set(Mood.MOMENT, now, moment_ms(Moment.CURIOUS))

    def talk(self, now: int, ms: int) -> None:
        """She starts speaking, for at most ``ms`` in case ``quiet`` never comes.

        Livelier or sulking moods aren't interrupted; calling it again while
        talking extends the limit.
        """
        if self.mood == Mood.TALKING:
            self._until = now + ms
        elif self.mood in (Mood.IDLE, Mood.MOMENT, Mood.WANDER):
            self._set(Mood.TALKING, now, ms)

    def quiet(self, now: int) -> None:
        """The voice stopped."""
        if self.mood == Mood.TALKING:
            self._set(Mood.IDLE, now, None)

    def request_mood(self, mood: Mood, now: int, ttl_ms: int | None = None) -> bool:
        """An agent request. Returns False (refused) while she's held, falling or dizzy.

        HAPPY lasts HAPPY_MS unless ``ttl_ms`` says otherwise; the others last
        until ``ttl_ms`` passes or another request (IDLE ends it).
        """
        if mood not in AGENT_MOODS:
            raise ValueError(f"the agent can't request {mood}")
        if self.mood in REFUSE_REQUESTS:
            return False
        if mood == Mood.HAPPY:
            self._pokes.clear()
            self._set(Mood.HAPPY, now, HAPPY_MS if ttl_ms is None else ttl_ms)
        elif mood == Mood.IDLE:
            self._set(Mood.WALKING if self.away_from_home else Mood.IDLE, now, None)
        else:
            self._set(mood, now, ttl_ms)
        return True

    def perform(self, mood: Mood, now: int, ms: int | None, moment: Moment | None = None) -> bool:
        """Kryo picked a pose (the right-click wheel): play ``mood`` (with ``moment`` for
        MOMENT) for ``ms``, or until something else happens if None. Refused while she's held,
        falling or dizzy. While performing, the automatic rules leave her be: a dance needs no
        music, a sleep isn't ended by the cursor lingering near her (a poke or a drag still
        is), and no idle moment or music interrupts. The next transition ends it."""
        if self.mood in REFUSE_REQUESTS:
            return False
        if moment is not None:
            self.moment = moment
        self._pokes.clear()
        self._set(mood, now, ms)
        self.performing = True
        return True

    def long_press(self, now: int) -> None:
        if self.busy:
            return
        self._pokes.clear()
        self._set(Mood.HAPPY, now, HAPPY_MS)

    def grab(self, now: int) -> None:
        self._pokes.clear()
        self._set(Mood.HELD, now, None)

    def release(self, now: int) -> None:
        if self.mood == Mood.HELD:
            self._set(Mood.FALLING, now, None)

    def land(self, now: int, flat: bool = False, high: bool = False, hurt: bool = False) -> None:
        """She hit the floor (first contact of a fall). Saber's rules (2026-10-26):
        ``hurt`` (she was thrown, or slammed into a screen edge) -> tears; ``flat`` (dropped while
        carried lying flat) or ``high`` (dropped more than half the screen's height) -> the hard
        landing; anything lower -> the soft one. No dizziness after falls any more."""
        if hurt:
            self._set(Mood.CRYING, now, CRY_MS)
        elif flat:
            self._set(Mood.HARD_LANDING, now, HARD_LANDING_MS)
        elif high:
            self._set(Mood.HARD_LANDING, now, HIGH_LANDING_MS)
        else:
            self._set(Mood.SOFT_LANDING, now, SOFT_LANDING_MS)

    def tick(self, now: int, quiet_for_ms: int = 0, music: bool = False) -> None:
        """Advances time. ``quiet_for_ms``: how long since she was last touched;
        ``music``: whether media is playing."""
        if now >= self._until:
            self._set(Mood.WALKING if self.away_from_home else Mood.IDLE, now, None)
        if self.performing:
            return  # a pose Kryo picked: it runs its time (or until a poke, a drag, the agent)
        m = self.mood
        if m == Mood.SLEEPING:
            if quiet_for_ms < WAKE_TOUCH_MS:
                self._set(Mood.SURPRISED, now, SURPRISE_MS)  # woken with a start
            elif music:
                self._set(Mood.DANCING, now, None)
        elif m == Mood.DANCING:
            if not music:
                self._set(Mood.IDLE, now, None)
        elif m in (Mood.IDLE, Mood.MOMENT):
            if music and not self.away_from_home:
                self._set(Mood.DANCING, now, None)
            elif m == Mood.IDLE and self.away_from_home:
                self._set(Mood.WALKING, now, None)
            elif m == Mood.IDLE and quiet_for_ms >= self.sleep_after_ms:
                self._set(Mood.SLEEPING, now, None)
            elif m == Mood.IDLE and now >= self._next_moment_at:
                self._start_moment(now)

    def arrived(self, now: int) -> None:
        """Called by the window code when a walk (home or wander) reaches its target."""
        if self.mood in (Mood.WALKING, Mood.WANDER):
            self._set(Mood.IDLE, now, None)

    def _start_moment(self, now: int) -> None:
        if self._next_moment_at < 0:
            # First idle after start: wait before the first moment.
            self._next_moment_at = now + self._gap()
            return
        if self._rng.random() < WANDER_CHANCE:
            sign = 1.0 if self._rng.random() < 0.5 else -1.0
            self.wander_px = sign * (40.0 + self._rng.random() * 80.0)
            self._set(Mood.WANDER, now, None)
        else:
            moments = list(Moment)
            self.moment = moments[self._rng.randrange(len(moments))]
            self._set(Mood.MOMENT, now, moment_ms(self.moment))
        self._next_moment_at = now + self._gap()

    def _gap(self) -> int:
        lo, hi = self.moment_gap_ms
        return lo + self._rng.randrange(max(1, hi - lo))

    def _set(self, mood: Mood, now: int, duration_ms: int | None) -> None:
        self.performing = False  # any transition ends a picked pose (perform sets it again)
        self.mood = mood
        self.since = now
        self._until = NEVER if duration_ms is None else now + duration_ms
