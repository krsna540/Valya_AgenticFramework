import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_current_user_flexible
from app.core.config import settings
from app.core.database import get_db
from app.models.file import UploadedFile
from app.models.user import User
from app.schemas.file import FileRead

router = APIRouter(prefix="/files", tags=["files"])


def _upload_root() -> Path:
    root = Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


@router.post("/upload", response_model=FileRead, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadedFile:
    file_id = uuid.uuid4()
    dest = _upload_root() / f"{file_id}_{file.filename}"

    size_bytes = 0
    with open(dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size_bytes += len(chunk)
            if size_bytes > settings.max_upload_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File exceeds {settings.max_upload_bytes // (1024 * 1024)} MB limit",
                )
            out.write(chunk)

    record = UploadedFile(
        id=file_id,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        size_bytes=size_bytes,
        storage_path=str(dest),
        uploaded_by=current_user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/{file_id}", response_model=FileRead)
def get_file_metadata(
    file_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> UploadedFile:
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return record


@router.get("/{file_id}/content")
def get_file_content(
    file_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user_flexible)
) -> FileResponse:
    record = db.get(UploadedFile, file_id)
    if record is None or not Path(record.storage_path).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(record.storage_path, media_type=record.content_type, filename=record.filename)
