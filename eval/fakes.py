"""A scripted stand-in for the OpenAI client, for offline tests of the agent loop."""

import json
import threading
from types import SimpleNamespace as NS


class ScriptedModel:
    """plays back tool calls, then answers in text, and records the messages it was sent

    script items are SQL strings, each a run_sql call, or (tool name, args) pairs
    gate, when given, is an event every call waits on, to hold an answer in flight
    entered, when given, is set as soon as a call arrives, so a test knows the turn has started
    """

    def __init__(
        self, script=(), sent: list | None = None,
        gate: threading.Event | None = None, entered: threading.Event | None = None,
    ):
        self.script = list(script)
        self.sent = sent if sent is not None else []
        self.gate = gate
        self.entered = entered
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kwargs):
        if self.entered is not None:
            self.entered.set()
        if self.gate is not None:
            self.gate.wait(timeout=10)
        self.sent.append([dict(m) for m in kwargs["messages"]])
        if self.script:
            item = self.script.pop(0)
            name, args = ("run_sql", {"sql": item}) if isinstance(item, str) else item
            call = NS(id=f"call_{len(self.sent)}", function=NS(name=name, arguments=json.dumps(args)))
            message = NS(content=None, tool_calls=[call], refusal=None)
        else:
            message = NS(content="ok", tool_calls=None, refusal=None)
        return NS(choices=[NS(message=message)], usage=NS(prompt_tokens=0, completion_tokens=0))
