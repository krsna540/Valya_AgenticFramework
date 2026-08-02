"""Durability layer — where a run executes.

`DurableRunner` is the port; two adapters implement it:

  * `LocalRunner` — in-process. The right choice for interactive chat, where
    the caller is holding an open SSE connection anyway: a durable envelope
    buys nothing if the thing waiting for the result dies with the process.
  * `TemporalRunner` — a Temporal workflow. The right choice for long or
    resumable work: the run survives a backend restart, retries activities
    with a real policy, and can pause on a human-in-the-loop signal.

`get_runner()` picks between them from settings, so nothing above this
package needs to know which one is active.

Temporal imports are deliberately deferred into the adapter rather than done
at package import. `temporalio` pulls in a Rust core extension, and a
deployment running with `TEMPORAL_ENABLED=false` — including the test suite —
should not need it importable at all.
"""
from app.agents.durable.base import DurableRunner, RunHandle
from app.agents.durable.local import LocalRunner
from app.agents.durable.selector import get_runner

__all__ = ["DurableRunner", "LocalRunner", "RunHandle", "get_runner"]
