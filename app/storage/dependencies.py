from typing import Annotated

from fastapi import Depends

from app.core.config import get_settings
from app.storage.local import LocalFileStorage

settings = get_settings()
file_storage = LocalFileStorage(settings.upload_dir)


def get_file_storage() -> LocalFileStorage:
    return file_storage


FileStorage = Annotated[LocalFileStorage, Depends(get_file_storage)]
