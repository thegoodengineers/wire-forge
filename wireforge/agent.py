"""A small tool-use loop over the Messages API, with metrics for the model comparison."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import anthropic

from . import config


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[..., str]

    def definition(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


@dataclass
class RunStats:
    model: str
    turns: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    wall_s: float = 0.0
    stop: str = ""


@dataclass
class Agent:
    name: str
    model: str
    system: str
    tools: list[Tool]
    log_path: Path
    stats: RunStats = field(init=False)
    finished: bool = False
    messages: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.stats = RunStats(model=self.model)
        self.client = anthropic.Anthropic(**config.anthropic_client_kwargs())
        self._by_name = {t.name: t for t in self.tools}
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _log(self, kind: str, data: Any) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "agent": self.name, "kind": kind, "data": data}, default=str) + "\n")

    def _say(self, msg: str) -> None:
        print(f"[{self.name}:{self.model}] {msg}", flush=True)

    def _call_tool(self, block) -> dict:
        tool = self._by_name.get(block.name)
        self.stats.tool_calls += 1
        args = block.input if isinstance(block.input, dict) else {}
        self._say(f"-> {block.name}({json.dumps(args, default=str)[:140]})")
        try:
            if tool is None:
                raise ValueError(f"unknown tool {block.name}")
            result = tool.fn(**args)
            is_error = False
        except Exception as exc:  # the model sees the error and can recover
            result = f"{type(exc).__name__}: {exc}"
            is_error = True
            self.stats.tool_errors += 1
        self._log("tool", {"name": block.name, "input": args, "result": result[:4000], "error": is_error})
        return {"type": "tool_result", "tool_use_id": block.id, "content": result, "is_error": is_error}

    def run(self, task: str, max_turns: int = config.MAX_AGENT_TURNS) -> RunStats:
        t0 = time.time()
        if self.messages and self.messages[-1]["role"] == "user":
            # Stopped on the turn limit right after tool results: join rather than send two user turns.
            self.messages[-1]["content"].append({"type": "text", "text": task})
        else:
            self.messages.append({"role": "user", "content": task})
        self._log("task", task)
        while self.stats.turns < max_turns and not self.finished:
            self.stats.turns += 1
            with self.client.messages.stream(
                model=self.model,
                max_tokens=32000,
                system=self.system,
                tools=[t.definition() for t in self.tools],
                messages=self.messages,
                thinking={"type": "adaptive", "display": "summarized"},
                output_config={"effort": config.effort_for(self.model)},
                cache_control={"type": "ephemeral"},
            ) as stream:
                resp = stream.get_final_message()
            u = resp.usage
            self.stats.input_tokens += u.input_tokens
            self.stats.output_tokens += u.output_tokens
            # input_tokens counts only the uncached part; both cache figures are needed for real cost.
            self.stats.cache_read_tokens += getattr(u, "cache_read_input_tokens", 0) or 0
            self.stats.cache_write_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0
            # Append the whole content, thinking blocks included: the history must stay unedited.
            self.messages.append({"role": "assistant", "content": resp.content})
            for b in resp.content:
                if b.type == "thinking" and b.thinking:
                    self._log("thinking", b.thinking)
                elif b.type == "text" and b.text.strip():
                    self._say(b.text.strip()[:300])
                    self._log("text", b.text)
            if resp.stop_reason == "refusal":
                self.stats.stop = "refusal"
                break
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if tool_uses:
                results = [self._call_tool(b) for b in tool_uses]
                self.messages.append({"role": "user", "content": results})
                continue
            if resp.stop_reason == "max_tokens":
                self.messages.append({"role": "user", "content": "Continue."})
                continue
            self.stats.stop = "end_turn"
            break
        if not self.stats.stop:
            self.stats.stop = "finished" if self.finished else "turn_limit"
        self.stats.wall_s = round(time.time() - t0, 1)
        self._log("stats", self.stats.__dict__)
        return self.stats

    def nudge(self, text: str, max_turns: int = config.MAX_AGENT_TURNS) -> RunStats:
        """Continue the same conversation with a new user message (repair rounds)."""
        self.stats.stop = ""
        prev_wall = self.stats.wall_s
        stats = self.run(text, max_turns=self.stats.turns + max_turns)
        stats.wall_s = round(prev_wall + stats.wall_s, 1)
        return stats
