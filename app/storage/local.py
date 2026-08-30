import hashlib
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

CHUNK_SIZE = 64 * 1024
logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Base error for controlled file-storage failures."""


class EmptyUpload(StorageError):
    """Raised when an uploaded stream contains no bytes."""


class UploadTooLarge(StorageError):
    """Raised when streamed bytes exceed the configured limit."""


class StorageConflict(StorageError):
    """Raised when a generated storage key already exists."""


class StoredFileMissing(StorageError):
    """Raised when expected stored bytes do not exist."""


class StorageUnavailable(StorageError):
    """Raised when the local filesystem cannot complete an operation."""


@dataclass(frozen=True)
class StoredFile:
    size_bytes: int
    checksum_sha256: str


@dataclass(frozen=True)
class StagedDeletion:
    original_path: Path
    staged_path: Path


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def save(
        self,
        source: BinaryIO,
        storage_key: str,
        max_bytes: int,
    ) -> StoredFile:
        destination = self._path_for(storage_key)
        size_bytes = 0
        checksum = hashlib.sha256()

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as target:
                while chunk := source.read(CHUNK_SIZE):
                    size_bytes += len(chunk)
                    if size_bytes > max_bytes:
                        raise UploadTooLarge
                    checksum.update(chunk)
                    target.write(chunk)
            if size_bytes == 0:
                raise EmptyUpload
        except (EmptyUpload, UploadTooLarge):
            self._remove_file(destination)
            raise
        except FileExistsError as error:
            raise StorageConflict from error
        except OSError as error:
            self._remove_file(destination)
            raise StorageUnavailable from error
        except Exception:
            self._remove_file(destination)
            raise

        return StoredFile(size_bytes=size_bytes, checksum_sha256=checksum.hexdigest())

    def delete(self, storage_key: str, *, missing_ok: bool = False) -> None:
        path = self._path_for(storage_key)
        try:
            path.unlink(missing_ok=missing_ok)
            self._remove_empty_parents(path.parent)
        except FileNotFoundError as error:
            raise StoredFileMissing from error
        except OSError as error:
            raise StorageUnavailable from error

    def inspect(self, storage_key: str) -> StoredFile:
        path = self._path_for(storage_key)
        size_bytes = 0
        checksum = hashlib.sha256()
        try:
            with path.open("rb") as source:
                while chunk := source.read(CHUNK_SIZE):
                    size_bytes += len(chunk)
                    checksum.update(chunk)
        except FileNotFoundError as error:
            raise StoredFileMissing from error
        except OSError as error:
            raise StorageUnavailable from error
        return StoredFile(size_bytes=size_bytes, checksum_sha256=checksum.hexdigest())

    @contextmanager
    def open_binary(self, storage_key: str) -> Iterator[BinaryIO]:
        path = self._path_for(storage_key)
        try:
            with path.open("rb") as source:
                yield source
        except FileNotFoundError as error:
            raise StoredFileMissing from error
        except OSError as error:
            raise StorageUnavailable from error

    def stage_delete(self, storage_key: str) -> StagedDeletion:
        original_path = self._path_for(storage_key)
        staged_path = self._path_for(f".trash/{uuid.uuid4()}")
        try:
            staged_path.parent.mkdir(parents=True, exist_ok=True)
            original_path.replace(staged_path)
            self._remove_empty_parents(original_path.parent)
        except FileNotFoundError as error:
            raise StoredFileMissing from error
        except OSError as error:
            raise StorageUnavailable from error
        return StagedDeletion(original_path=original_path, staged_path=staged_path)

    def stage_many(self, storage_keys: list[str]) -> list[StagedDeletion]:
        staged: list[StagedDeletion] = []
        try:
            for storage_key in storage_keys:
                staged.append(self.stage_delete(storage_key))
        except StorageError:
            self.restore_many(staged)
            raise
        return staged

    def restore_many(self, staged_deletions: list[StagedDeletion]) -> None:
        first_error: StorageError | None = None
        for deletion in reversed(staged_deletions):
            try:
                deletion.original_path.parent.mkdir(parents=True, exist_ok=True)
                deletion.staged_path.replace(deletion.original_path)
            except OSError as error:
                first_error = first_error or StorageUnavailable(str(error))
        if first_error is not None:
            raise first_error

    def finalize_many(self, staged_deletions: list[StagedDeletion]) -> None:
        first_error: StorageError | None = None
        for deletion in staged_deletions:
            try:
                deletion.staged_path.unlink()
                self._remove_empty_parents(deletion.staged_path.parent)
            except FileNotFoundError:
                continue
            except OSError as error:
                first_error = first_error or StorageUnavailable(str(error))
        if first_error is not None:
            raise first_error

    def _path_for(self, storage_key: str) -> Path:
        relative_path = Path(storage_key)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise StorageConflict("Storage keys must stay inside the configured root.")
        path = (self.root / relative_path).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as error:
            raise StorageConflict("Storage keys must stay inside the configured root.") from error
        return path

    def _remove_file(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
            self._remove_empty_parents(path.parent)
        except OSError:
            logger.exception("Failed to clean a partial stored file")

    def _remove_empty_parents(self, directory: Path) -> None:
        while directory != self.root:
            try:
                directory.rmdir()
            except OSError:
                break
            directory = directory.parent
