"""The scripted assistant used by the assistant tests."""
import json
import threading
from contextvars import ContextVar
from types import SimpleNamespace

import pytest


@pytest.fixture
def assistant_rig(monkeypatch):
    from app.schemas.assistant import AssistantRequest, Evidence
    from app.services import scientific_assistant as assistant

    rig = SimpleNamespace(
        calls=[], records=[], reads=[], plans=[],
        evidence=[Evidence(tool="test", status="available", text="result_answer_summary|count=12")],
        cancelled=threading.Event(), revision=[1], profile={"value": ("compact", 2, 600)},
    )
    monkeypatch.setattr(assistant, "runtime_cache_version", lambda: rig.revision[0])
    monkeypatch.setattr(assistant, "provider_deadline", ContextVar("test_assistant_deadline", default=None))
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: rig.profile["value"])
    monkeypatch.setattr(assistant, "assistant_prompt_budget", lambda *args: (11136, 15232))

    def read(*args):
        rig.reads.append(args)
        rig.plans.append(args[1])
        return rig.evidence

    def run(replies, message="Explain this plot", **fields):
        pending = iter(replies)

        def complete(request, instruction, data, **kwargs):
            payload = json.loads(data)
            rig.calls.append(payload)
            rig.records.append({"data": payload, "schema": kwargs.get("schema"), "instruction": instruction})
            reply = next(pending)
            if callable(reply):
                reply = reply()
            if isinstance(reply, Exception):
                raise reply
            return "synthetic", reply

        monkeypatch.setattr(assistant, "assistant_completion", complete)
        view = fields.pop("view", {"module": "qc.cv"})
        return assistant.assistant_step(
            AssistantRequest(message=message, model="synthetic", view=view, **fields), rig.cancelled)

    monkeypatch.setattr(assistant, "scientific_evidence", read)
    rig.run = run
    return rig
