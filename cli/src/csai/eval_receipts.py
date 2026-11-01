"""Private publication coordination, separate from immutable evaluation journals."""

import os
from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


class PublicationReceipt(BaseModel):
    """Submission outcome, not an evaluation result."""

    model_config = ConfigDict(extra="forbid")

    key: str
    evaluation_id: str
    run_id: str | None = None


class ReceiptStore:
    """Atomically retain submission receipts under an exclusive publisher lock."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> PublicationReceipt | None:
        """Read only the private receipt, never a measurement artifact."""
        if self.path.is_symlink():
            raise ValueError("Refusing a symlink publication receipt.")
        return (
            PublicationReceipt.model_validate_json(self.path.read_text("utf-8"))
            if self.path.exists()
            else None
        )

    def write(self, receipt: PublicationReceipt) -> None:
        """Flush a receipt and atomically replace the previous outcome."""
        if self.path.is_symlink():
            raise ValueError("Refusing a symlink publication receipt.")
        pending = self.path.with_name(f".{self.path.name}.{uuid4().hex}.pending")
        try:
            descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(receipt.model_dump_json() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            pending.replace(self.path)
            descriptor = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if pending.exists():
                pending.unlink()


def _private_directory(directory: Path) -> None:
    if not directory.parent.is_dir():
        _private_directory(directory.parent)
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        if not directory.is_dir():
            raise
    else:
        descriptor = os.open(directory.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    directory.chmod(0o700)


@contextmanager
def publication_receipt(directory: Path, key: str) -> Generator[ReceiptStore]:
    """Serialize local publishers and retain ambiguous submissions without resubmitting."""
    if os.name != "posix":
        raise OSError("Private publication coordination requires POSIX filesystem locks.")
    import fcntl

    if any(parent.is_symlink() for parent in (directory, *directory.parents)):
        raise ValueError("Refusing a symlink publication directory.")
    _private_directory(directory)
    descriptor = os.open(directory / f"{key}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield ReceiptStore(directory / f"{key}.json")
    finally:
        os.close(descriptor)
