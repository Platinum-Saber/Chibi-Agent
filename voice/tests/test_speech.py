import asyncio

import numpy as np

from chibi_voice.speech import Item, SpeechQueue


class Fake:
    """Synthesiser and player that log what happened, with controllable durations."""

    def __init__(self, render_s=0.02, play_s=0.05, fail=()):
        self.render_s, self.play_s, self.fail = render_s, play_s, set(fail)
        self.log: list[tuple] = []
        self.states: list[tuple[str, str]] = []

    async def render(self, item):
        self.log.append(("render", item.utt_id))
        await asyncio.sleep(self.render_s)
        if item.utt_id in self.fail:
            raise RuntimeError("boom")
        self.log.append(("rendered", item.utt_id))
        return np.array([len(item.utt_id)], np.float32), 24000

    async def play(self, audio, sr, on_start):
        await on_start()
        self.log.append(("play", self.states[-1][0]))
        await asyncio.sleep(self.play_s)

    async def emit(self, utt_id, state):
        self.states.append((utt_id, state))


async def drain(q: SpeechQueue, timeout=2.0):
    async def wait():
        while q.busy:
            await asyncio.sleep(0.005)
    await asyncio.wait_for(wait(), timeout)


async def test_plays_in_order_with_start_end():
    f = Fake()
    q = SpeechQueue(f.render, f.play, f.emit)
    q.start()
    for u in ("a", "b", "c"):
        q.submit(Item(u, u))
    await drain(q)
    assert f.states == [("a", "start"), ("a", "end"), ("b", "start"), ("b", "end"),
                        ("c", "start"), ("c", "end")]
    await q.close()


async def test_renders_next_while_current_plays():
    f = Fake(render_s=0.01, play_s=0.1)
    q = SpeechQueue(f.render, f.play, f.emit)
    q.start()
    q.submit(Item("a", "a"))
    q.submit(Item("b", "b"))
    await drain(q)
    # "b" was rendered while "a" was playing.
    i_play_a = f.log.index(("play", "a"))
    i_rendered_b = f.log.index(("rendered", "b"))
    i_play_b = f.log.index(("play", "b"))
    assert i_play_a < i_rendered_b < i_play_b
    await q.close()


async def test_slow_render_keeps_order():
    f = Fake(render_s=0.05, play_s=0.01)
    q = SpeechQueue(f.render, f.play, f.emit)
    q.start()
    for u in ("1", "2", "3", "4"):
        q.submit(Item(u, u))
    await drain(q)
    assert [u for u, s in f.states if s == "start"] == ["1", "2", "3", "4"]
    await q.close()


async def test_stop_cancels_current_and_queued_then_recovers():
    f = Fake(render_s=0.01, play_s=0.5)
    q = SpeechQueue(f.render, f.play, f.emit)
    q.start()
    for u in ("a", "b", "c"):
        q.submit(Item(u, u))
    while ("a", "start") not in f.states:
        await asyncio.sleep(0.005)
    await q.stop()
    assert f.states == [("a", "start"), ("a", "cancel"), ("b", "cancel"), ("c", "cancel")]
    assert not q.busy
    # The queue works again after a stop.
    f.play_s = 0.01
    f.states.clear()
    q.submit(Item("d", "d"))
    await drain(q)
    assert f.states == [("d", "start"), ("d", "end")]
    await q.close()


async def test_stop_while_idle_is_harmless():
    f = Fake()
    q = SpeechQueue(f.render, f.play, f.emit)
    q.start()
    await q.stop()
    assert f.states == []
    await q.close()


async def test_render_failure_cancels_that_item_only():
    f = Fake(fail={"b"})
    q = SpeechQueue(f.render, f.play, f.emit)
    q.start()
    for u in ("a", "b", "c"):
        q.submit(Item(u, u))
    await drain(q)
    assert ("b", "cancel") in f.states
    assert [u for u, s in f.states if s == "end"] == ["a", "c"]
    await q.close()
