"""Resolves an Agent.model_name string to a ModelRoute catalog entry and
computes a real dollar cost from real token counts. Used by
app/api/routes/chat.py right after a turn finishes streaming — see
app/models/usage_event.py's docstring for what "real" means here (the
token counts are the same ones the stream itself produced, not estimated
after the fact).

DEFAULT_COST_PER_1M is the fallback rate for an Agent whose model_name
doesn't match any row in the catalog (e.g. this app's own "stub-echo"
default, or a name a Super Admin hasn't onboarded yet) — kept low and
clearly documented rather than silently recording $0, since $0 would make
"cost by tenant" look like free usage rather than "unpriced usage".
"""
from sqlalchemy.orm import Session

from app.models.model_route import ModelRoute

DEFAULT_COST_PER_1M_INPUT = 1.00
DEFAULT_COST_PER_1M_OUTPUT = 2.00


def find_model_route(db: Session, model_name: str) -> ModelRoute | None:
    return db.query(ModelRoute).filter(ModelRoute.name == model_name).first()


def estimate_cost_usd(model_route: ModelRoute | None, input_tokens: int, output_tokens: int) -> float:
    input_rate = model_route.input_cost_per_1m if model_route else DEFAULT_COST_PER_1M_INPUT
    output_rate = (
        model_route.output_cost_per_1m
        if model_route and model_route.output_cost_per_1m is not None
        else DEFAULT_COST_PER_1M_OUTPUT
    )
    return round((input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate, 6)
