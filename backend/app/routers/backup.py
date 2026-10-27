"""Export and import of careers (see services/backup)."""
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.services import backup

router = APIRouter(prefix="/api/backup", tags=["backup"])


def _fail(e: backup.BackupError) -> HTTPException:
    return HTTPException(e.status_code, str(e))


@router.get("/export")
def export(player_id: int | None = None) -> Response:
    try:
        data, name = backup.export(player_id)
    except backup.BackupError as e:
        raise _fail(e) from e
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.post("/inspect")
async def inspect(request: Request) -> dict:
    """What an export contains, before importing it (the body is the file itself)."""
    try:
        return backup.inspect_file(await request.body())
    except backup.BackupError as e:
        raise _fail(e) from e


@router.post("/import")
async def import_(request: Request) -> dict:
    """Replace the database with the export in the body; the current one is kept under data/backups."""
    data = await request.body()
    try:
        return backup.import_(data)
    except backup.BackupError as e:
        raise _fail(e) from e
