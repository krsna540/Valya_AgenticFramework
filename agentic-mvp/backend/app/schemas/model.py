import uuid

from pydantic import BaseModel


class ModelInfo(BaseModel):
    """A selectable chat target. In this app a 'model' is an active Agent —
    see the '@ picks an Agent' design decision in the chat feature notes."""

    id: uuid.UUID
    name: str
    model_name: str
    description: str | None
