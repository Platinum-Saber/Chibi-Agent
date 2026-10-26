"""Tool selection with fake embeddings: one axis per family, so similarity is exact."""
from chibi_agent import tools
from chibi_agent.llm import Chunk
from chibi_agent.orchestrator import Orchestrator
from chibi_agent.persona import system_prompt
from chibi_agent.tools.runner import Runner
from chibi_agent.tools.select import CORE, FAMILIES, FAMILY_OF, ToolPicker

from test_tools import AutoGate, FakeHub

REG = tools.load_all()
NAMES = list(FAMILIES)


def axis(*weights: tuple[str, float], rest: float = 0.01) -> list[float]:
    """Cosine normalises, so `rest` (an unrelated axis) is what makes a weak match weak."""
    v = [0.0] * (len(NAMES) + 1)
    v[-1] = rest
    for f, w in weights:
        v[NAMES.index(f)] = w
    return v


class FakeEmbed:
    """Descriptors map to their family's axis; queries are looked up in `queries`."""

    def __init__(self, queries=None, fail=False):
        self.queries, self.fail, self.calls = queries or {}, fail, 0

    async def __call__(self, texts, query=False):
        self.calls += 1
        if self.fail:
            raise ConnectionError("ollama down")
        if not query:
            return [axis((f, 1.0)) for f in NAMES]
        return [self.queries[t] for t in texts]


def families(names):
    return {FAMILY_OF.get(n) for n in names} - {None}


def test_every_tool_is_in_exactly_one_family():
    listed = [t for ts, _ in FAMILIES.values() for t in ts]
    assert sorted(listed) == sorted(REG)
    assert CORE <= set(REG)


async def test_picks_top_families_plus_core_in_registry_order():
    p = ToolPicker(FakeEmbed(), {"families": 2, "margin": 0.0})
    assert await p.warm()
    names = p.pick(axis(("mail", 0.9), ("calendar", 0.6), ("web", 0.3)))
    assert families(names) == {"mail", "calendar", "screen", "memory", "windows"}  # core brings 3 tools
    assert set(names) == set(FAMILIES["mail"][0]) | set(FAMILIES["calendar"][0]) | CORE
    assert names == [n for n in REG if n in names]


async def test_margin_takes_a_close_runner_up():
    p = ToolPicker(FakeEmbed(), {"families": 1, "margin": 0.05})
    await p.warm()
    names = p.pick(axis(("files", 0.80), ("shell", 0.77), ("web", 0.5)))
    assert {"files", "shell"} <= families(names) and "web" not in families(names)


async def test_unsure_or_cold_means_every_tool():
    p = ToolPicker(FakeEmbed(), {"min_sim": 0.5})
    assert p.pick(axis(("mail", 0.9))) is None  # not warmed yet
    await p.warm()
    assert p.pick(axis(("mail", 0.3), rest=0.95)) is None
    assert p.pick(None) is None


async def test_previous_turn_and_sticky_tools_carry_over():
    p = ToolPicker(FakeEmbed(), {"families": 1, "margin": 0.0})
    await p.warm()
    follow_up = axis(("media", 0.5), rest=0.85)  # "read the second one": weak on its own
    names = p.pick(follow_up, prev=axis(("mail", 0.9), rest=0.44))
    assert "mail" in families(names)  # 0.7 * 0.9 beats 0.5
    names = p.pick(axis(("web", 0.9)), sticky={"search_files"})
    assert {"web", "files"} <= families(names)


async def test_disabled_or_failing_embedder_sends_everything():
    off = ToolPicker(FakeEmbed(), {"select": False})
    assert await off.query_vec("hi") is None
    down = ToolPicker(FakeEmbed(fail=True))
    assert await down.query_vec("hi") is None and down.pick(axis(("mail", 1))) is None


def test_typical_pick_frees_most_of_the_prompt():
    full = system_prompt(tools.listing())
    pick = sorted(CORE | set(FAMILIES["mail"][0]) | set(FAMILIES["calendar"][0]) | set(FAMILIES["files"][0]))
    small = system_prompt(tools.listing(pick), partial=True)
    assert len(small) < 2400 < len(full)  # the persona itself is ~2 k
    assert len(str(tools.schemas(pick))) < len(str(tools.schemas())) / 2


class ScriptLLM:
    def __init__(self, script):
        self.script, self.calls = script, []

    async def chat(self, messages, tools=None, think=False):
        self.calls.append(([t["function"]["name"] for t in tools or []], list(messages)))
        for chunk in self.script[min(len(self.calls), len(self.script)) - 1]:
            yield chunk
        yield Chunk(done=True)


class SpyMemory:
    def __init__(self):
        self.vecs = []

    async def recall(self, query, vec=None):
        self.vecs.append(vec)
        return ""

    def log_turn(self, user, reply):
        pass


async def test_turn_sends_only_the_pick_and_shares_the_vector(tmp_path):
    q = axis(("mail", 0.9))
    picker = ToolPicker(FakeEmbed({"any new mail?": q}), {"families": 1, "margin": 0.0})
    llm = ScriptLLM([[Chunk(text="Answer. Nothing new, Saber.")]])
    mem = SpyMemory()
    o = Orchestrator(FakeHub(), llm, Runner(AutoGate(True), audit_file=tmp_path / "a.jsonl"), mem, picker=picker)
    o.start_turn("any new mail?")
    await o.turn
    sent, messages = llm.calls[0]
    assert set(sent) == set(FAMILIES["mail"][0]) | CORE
    assert "- mail_list:" in messages[0]["content"] and "- run_shell:" not in messages[0]["content"]
    assert mem.vecs == [q]
    assert picker.embed.calls == 2  # descriptors once, then the query: recall did not embed again


async def test_cant_with_a_subset_retries_once_with_every_tool(tmp_path):
    picker = ToolPicker(FakeEmbed({"empty the recycle bin list": axis(("files", 0.9))}),
                        {"families": 1, "margin": 0.0})
    llm = ScriptLLM([[Chunk(text="Answer. I cannot see the Recycle Bin, Saber.")],
                     [Chunk(tool_calls=[{"function": {"name": "get_time", "arguments": {}}}])],
                     [Chunk(text="Confirmed.")]])
    o = Orchestrator(FakeHub(), llm, Runner(AutoGate(True), audit_file=tmp_path / "a.jsonl"), picker=picker)
    o.start_turn("empty the recycle bin list")
    await o.turn
    assert "recycle_bin" not in llm.calls[0][0]
    assert set(llm.calls[1][0]) == set(REG)
    assert "every tool is available" in llm.calls[1][1][-1]["content"]
    assert o.recent_tools == [{"get_time"}]


async def test_ordinary_cant_does_not_retry(tmp_path):
    picker = ToolPicker(FakeEmbed({"do you have feelings?": axis(("memory", 0.9))}), {"families": 1})
    llm = ScriptLLM([[Chunk(text="Answer. I can't feel emotions the way you do, Saber.")]])
    o = Orchestrator(FakeHub(), llm, Runner(AutoGate(True), audit_file=tmp_path / "a.jsonl"), picker=picker)
    o.start_turn("do you have feelings?")
    await o.turn
    assert len(llm.calls) == 1
