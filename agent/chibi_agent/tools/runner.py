"""Runs tool calls: argument checks, the confirmation gate, timeouts, the audit log.

The gate asks the overlay (`confirm` -> HUD Yes/No) and also accepts a spoken
yes/no from the orchestrator. No answer within 60 s counts as no. A side-effect
tool can never run without a recorded yes.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
import uuid
from pathlib import Path

from chibi_shared import paths
from chibi_shared.protocol import Confirm, ConfirmResult

from . import REGISTRY, Result, Tool

log = logging.getLogger(__name__)
CONFIRM_TIMEOUT_S = 60.0
MAX_RESULT_CHARS = 4000


class Gate:
    def __init__(self, hub):
        self.hub = hub
        self.pending: dict[str, asyncio.Future] = {}

    async def ask(self, tool: Tool, args: dict) -> bool:
        call_id = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self.pending[call_id] = fut
        await self.hub.send("overlay", Confirm(call_id=call_id, tool=tool.name, summary=tool.summary(args),
                                               detail=json.dumps(args, ensure_ascii=False)[:300]))
        ok = False
        try:
            ok = await asyncio.wait_for(fut, CONFIRM_TIMEOUT_S)
            return ok
        except asyncio.TimeoutError:
            return False
        finally:
            self.pending.pop(call_id, None)
            # However it was answered (button, voice, timeout), the overlay drops the panel.
            await self.hub.send("overlay", ConfirmResult(call_id=call_id, ok=ok))

    def answer(self, call_id: str | None, ok: bool) -> bool:
        """From the overlay (call_id) or a spoken yes/no (None: the newest pending)."""
        if call_id is None and self.pending:
            call_id = next(reversed(self.pending))
        fut = self.pending.get(call_id or "")
        if fut and not fut.done():
            fut.set_result(ok)
            return True
        return False

    @property
    def waiting(self) -> bool:
        return bool(self.pending)


class Runner:
    def __init__(self, gate: Gate, audit_file: Path | None = None):
        self.gate = gate
        self.audit_file = audit_file or paths.DATA / "audit.jsonl"

    def _audit(self, **rec) -> None:
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), **rec}, ensure_ascii=False) + "\n")

    async def run(self, name: str, args: dict | None) -> Result:
        tool = REGISTRY.get(name)
        if tool is None:
            return Result(f"Error: there is no tool named {name}.")
        args = {k: str(v) for k, v in (args or {}).items() if k in tool.params}
        missing = [k for k, (_, req) in tool.params.items() if req and not args.get(k)]
        if missing:
            return Result(f"Error: missing argument(s): {', '.join(missing)}.")
        confirmed = None
        if tool.confirm:
            confirmed = await self.gate.ask(tool, args)
            if not confirmed:
                self._audit(tool=name, args=args, confirmed=False, status="declined")
                return Result("Kryo declined. Do not retry unless asked again.")
        t0 = time.perf_counter()
        try:
            if inspect.iscoroutinefunction(tool.fn):
                res = await asyncio.wait_for(tool.fn(**args), tool.timeout_s)
            else:
                res = await asyncio.wait_for(asyncio.to_thread(tool.fn, **args), tool.timeout_s)
            status = "ok"
        except asyncio.TimeoutError:
            res, status = Result(f"{name} timed out after {tool.timeout_s:.0f} s.", failed=True), "timeout"
        except Exception as e:  # tools report failures to the model, they don't crash the turn
            log.exception("tool %s failed", name)
            res, status = Result(f"{type(e).__name__}: {e}", failed=True), "error"
        if not isinstance(res, Result):
            res = Result(str(res))
        if len(res.text) > MAX_RESULT_CHARS:
            res.text = res.text[:MAX_RESULT_CHARS] + "\n[truncated]"
        if tool.side_effect:
            self._audit(tool=name, args=args, confirmed=confirmed, status=status,
                        ms=int((time.perf_counter() - t0) * 1000))
        return res
