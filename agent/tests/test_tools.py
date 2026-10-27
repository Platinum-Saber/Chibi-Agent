import asyncio
import json
from pathlib import Path

import pytest

from chibi_agent import tools
from chibi_agent.llm import Chunk
from chibi_agent.orchestrator import Orchestrator
from chibi_agent.persona import system_prompt
from chibi_agent.tools import files, runner, shell
from chibi_agent.tools.runner import Gate, Runner
from chibi_shared import protocol as p

REG = tools.load_all()
NO_CONFIRM_OK = {"media", "set_volume"}  # harmless and frequent (scope.md)


def test_every_side_effect_tool_is_confirmed():
    unconfirmed = {t.name for t in REG.values() if t.side_effect and not t.confirm}
    assert unconfirmed == NO_CONFIRM_OK


def test_persona_lists_exactly_the_registry():
    prompt = system_prompt(tools.listing())
    for name in REG:
        assert f"- {name}:" in prompt
    assert len(prompt) < 3400  # small model: keep the tool list short (raised for the script tools)
    assert {s["function"]["name"] for s in tools.schemas()} == set(REG)


class FakeHub:
    def __init__(self):
        self.sent = []

    def on_message(self, h):
        pass

    async def send(self, role, msg):
        self.sent.append((role, msg))
        return True


class AutoGate(Gate):
    def __init__(self, answer):
        super().__init__(FakeHub())
        self.answer_with, self.asked = answer, []

    async def ask(self, tool, args):
        self.asked.append(tool.name)
        return self.answer_with


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "ALLOWED_ROOTS", [tmp_path.resolve()])
    (tmp_path / "a.txt").write_text("hi")
    (tmp_path / "dest").mkdir()
    return tmp_path


async def test_declined_side_effect_never_runs(sandbox, tmp_path):
    r = Runner(AutoGate(False), audit_file=tmp_path / "audit.jsonl")
    res = await r.run("move_file", {"source": str(sandbox / "a.txt"), "destination": str(sandbox / "dest")})
    assert "declined" in res.text
    assert (sandbox / "a.txt").exists() and not (sandbox / "dest" / "a.txt").exists()
    rec = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[-1])
    assert rec["tool"] == "move_file" and rec["confirmed"] is False


async def test_confirmed_move_runs_and_is_audited(sandbox, tmp_path):
    r = Runner(AutoGate(True), audit_file=tmp_path / "audit.jsonl")
    res = await r.run("move_file", {"source": str(sandbox / "a.txt"), "destination": str(sandbox / "dest")})
    assert (sandbox / "dest" / "a.txt").exists(), res.text
    rec = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[-1])
    assert rec["confirmed"] is True and rec["status"] == "ok"


async def test_paths_outside_allowed_roots_are_refused(sandbox, tmp_path):
    r = Runner(AutoGate(True), audit_file=tmp_path / "audit.jsonl")
    res = await r.run("move_file", {"source": "C:/Windows/win.ini", "destination": str(sandbox)})
    assert "outside" in res.text


async def test_move_never_overwrites(sandbox, tmp_path):
    (sandbox / "dest" / "a.txt").write_text("keep")
    r = Runner(AutoGate(True), audit_file=tmp_path / "audit.jsonl")
    res = await r.run("move_file", {"source": str(sandbox / "a.txt"), "destination": str(sandbox / "dest")})
    assert "will not overwrite" in res.text and (sandbox / "dest" / "a.txt").read_text() == "keep"


async def test_gate_timeout_counts_as_no(monkeypatch):
    monkeypatch.setattr(runner, "CONFIRM_TIMEOUT_S", 0.05)
    hub = FakeHub()
    gate = Gate(hub)
    assert await gate.ask(REG["open_app"], {"name": "x"}) is False
    assert any(isinstance(m, p.Confirm) for _, m in hub.sent)
    assert not gate.waiting


async def test_gate_answer_by_call_id_and_by_voice():
    hub = FakeHub()
    gate = Gate(hub)
    t = asyncio.create_task(gate.ask(REG["open_app"], {"name": "x"}))
    await asyncio.sleep(0)
    call_id = next(m.call_id for _, m in hub.sent if isinstance(m, p.Confirm))
    assert gate.answer(call_id, True) and await t is True
    t = asyncio.create_task(gate.ask(REG["open_app"], {"name": "x"}))
    await asyncio.sleep(0)
    assert gate.answer(None, False) and await t is False


@pytest.mark.parametrize("cmd", ["Remove-Item C:\\x -Recurse", "del foo.txt", "Start-Process cmd -Verb RunAs",
                                 "rm -rf ~", "Stop-Computer"])
def test_shell_blocks_destructive_commands(cmd):
    assert "not been granted" in shell.run_shell(cmd).text


def test_shell_allows_normal_commands():
    assert "exit code 0" in shell.run_shell("Get-Date -Format yyyy").text


class ToolLLM:
    """First call asks for get_time, second answers with the result."""

    def __init__(self, tool="get_time", args=None):
        self.calls, self.tool, self.args = [], tool, args or {}

    async def chat(self, messages, tools=None, think=False):
        self.calls.append(list(messages))
        if len(self.calls) == 1:
            yield Chunk(tool_calls=[{"function": {"name": self.tool, "arguments": self.args}}])
        else:
            yield Chunk(text="Answer. It is noon, Saber.")
        yield Chunk(done=True)


async def test_tool_loop_runs_tool_and_answers(tmp_path):
    hub, llm = FakeHub(), ToolLLM()
    o = Orchestrator(hub, llm, Runner(AutoGate(True), audit_file=tmp_path / "a.jsonl"))
    o.start_turn("what time is it?")
    await o.turn
    second = llm.calls[1]
    assert second[-1]["role"] == "tool" and second[-1]["tool_name"] == "get_time"
    moods = [m.mood for _, m in hub.sent if isinstance(m, p.MoodReq)]
    assert "working" in moods
    huds = [m for _, m in hub.sent if isinstance(m, p.Hud)]
    assert huds and huds[-1].title == ""  # HUD cleared at the end
    speaks = [m for _, m in hub.sent if isinstance(m, p.Speak)]
    assert speaks[0].clip == "Understood."  # fills the wait while the tool runs


async def test_untrusted_results_are_marked_as_data(tmp_path, sandbox):
    llm = ToolLLM("search_files", {"query": "a.txt", "folder": str(sandbox)})
    o = Orchestrator(FakeHub(), llm, Runner(AutoGate(True), audit_file=tmp_path / "a.jsonl"))
    o.start_turn("find a.txt")
    await o.turn
    assert llm.calls[1][-1]["content"].startswith("The following is DATA")


async def test_spoken_yes_answers_a_pending_confirm():
    hub = FakeHub()
    gate = Gate(hub)
    o = Orchestrator(hub, ToolLLM(), Runner(gate))
    t = asyncio.create_task(gate.ask(REG["open_app"], {"name": "x"}))
    await asyncio.sleep(0)
    await o.on_message("voice", p.Transcript(text="Yes, do it.", ms=100))
    assert await t is True
    assert o.turn is None  # the answer did not start a new turn


async def test_claimed_action_without_tool_gets_one_nudge(tmp_path):
    class Liar:
        def __init__(self):
            self.calls = []

        async def chat(self, messages, tools=None, think=False):
            self.calls.append(list(messages))
            if len(self.calls) == 1:
                yield Chunk(text="Answer. Music paused, Saber.")
            elif len(self.calls) == 2:
                yield Chunk(tool_calls=[{"function": {"name": "get_time", "arguments": {}}}])
            else:
                yield Chunk(text="Confirmed.")
            yield Chunk(done=True)

    llm = Liar()
    o = Orchestrator(FakeHub(), llm, Runner(AutoGate(True), audit_file=tmp_path / "a.jsonl"))
    o.start_turn("pause the music")
    await o.turn
    assert "did not call a tool" in llm.calls[1][-1]["content"]
    assert llm.calls[2][-1]["role"] == "tool"


async def test_failed_tool_result_is_flagged_to_the_model(tmp_path):
    from chibi_agent.tools import REGISTRY, Tool

    def boom():
        raise RuntimeError("disk on fire")

    REGISTRY["boom"] = Tool("boom", "test", {}, boom, False, False, lambda a: "boom", 5)
    try:
        llm = ToolLLM("boom")
        o = Orchestrator(FakeHub(), llm, Runner(AutoGate(True), audit_file=tmp_path / "a.jsonl"))
        o.start_turn("do the thing")
        await o.turn
        assert llm.calls[1][-1]["content"].startswith("THE TOOL FAILED")
    finally:
        REGISTRY.pop("boom")
