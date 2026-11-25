import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .models import Session


def read_session(path: Path) -> Session:
    if not path.is_file():
        raise ValueError('A timing session must be a regular file.')
    with path.open('rb') as stream:
        data = stream.read(64_000_001)
    if len(data) > 64_000_000:
        raise ValueError('Timing session exceeds the 64 MB capture limit.')
    return Session.model_validate_json(data)


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temp:
            temp_name = temp.name
            temp.write(content)
        os.replace(temp_name, path)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def write_session(path: Path, session: Session) -> None:
    atomic_text(path, session.model_dump_json(indent=2) + "\n")
