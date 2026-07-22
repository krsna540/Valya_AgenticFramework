from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.agent import Agent
from app.models.user import User
from app.schemas.model import ModelInfo

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelInfo])
def list_models(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[ModelInfo]:
    """Selectable chat targets for the '@' picker and split-screen compare.
    A 'model' in this app is an active Agent (see chat feature design notes)."""
    agents = db.query(Agent).filter(Agent.is_active == True).order_by(Agent.name).all()  # noqa: E712
    return [
        ModelInfo(id=a.id, name=a.name, model_name=a.model_name, description=a.description) for a in agents
    ]
