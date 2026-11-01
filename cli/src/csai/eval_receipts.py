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


class SuiteReceipt(BaseModel):
    """Canonical suite identity or an ambiguous creation, independent of measurements."""

    model_config = ConfigDict(extra="forbid")

    key: str
    definition_key: str
    judge_model: str
    evaluation_id: str | None = None


class ReceiptStore[Receipt: BaseModel]:
    """Atomically retain submission receipts under an exclusive publisher lock."""

    def __init__(self, path: Path, schema: type[Receipt]) -> None:
        self.path = path
        self.schema = schema

    def read(self) -> Receipt | None:
        """Read only the private receipt, never a measurement artifact."""
        if self.path.is_symlink():
            raise ValueError("Refusing a symlink publication receipt.")
        return (
            self.schema.model_validate_json(self.path.read_text("utf-8"))
            if self.path.exists()
            else None
        )

    def write(self, receipt: Receipt) -> None:
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

    def clear(self) -> None:
        """Durably forget a confirmed rejected creation, never an ambiguous submission."""
        if self.path.is_symlink():
            raise ValueError("Refusing a symlink publication receipt.")
        self.path.unlink(missing_ok=True)
        descriptor = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


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
def _receipt_lock(directory: Path, key: str, *, wait: bool) -> Generator[Path]:
    if os.name != "posix":
        raise OSError("Private publication coordination requires POSIX filesystem locks.")
    import fcntl

    if any(parent.is_symlink() for parent in (directory, *directory.parents)):
        raise ValueError("Refusing a symlink publication directory.")
    _private_directory(directory)
    descriptor = os.open(directory / f"{key}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        yield directory / f"{key}.json"
    finally:
        os.close(descriptor)


@contextmanager
def publication_receipt(directory: Path, key: str) -> Generator[ReceiptStore[PublicationReceipt]]:
    """Serialize each measurement, rejecting another active submission of that measurement."""
    with _receipt_lock(directory, key, wait=False) as path:
        yield ReceiptStore(path, PublicationReceipt)


@contextmanager
def suite_receipt(directory: Path, key: str) -> Generator[ReceiptStore[SuiteReceipt]]:
    """Wait for endpoint-and-suite creation across independent measurement directories."""
    with _receipt_lock(directory, key, wait=True) as path:
        yield ReceiptStore(path, SuiteReceipt)


@contextmanager
def legacy_publication_receipt(
    directory: Path, key: str, *, allow_absent: bool = False
) -> Generator[ReceiptStore[PublicationReceipt] | None]:
    """Lock existing legacy evidence; optionally leave an absent default origin untouched."""
    if allow_absent and not any(path.is_symlink() for path in (directory, *directory.parents)):
        try:
            directory.stat(follow_symlinks=False)
        except FileNotFoundError:
            yield None
            return
    with _receipt_lock(directory, key, wait=False) as path:
        yield ReceiptStore(path, PublicationReceipt)
