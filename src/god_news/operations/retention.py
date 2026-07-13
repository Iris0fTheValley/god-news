from __future__ import annotations

import asyncio
import logging
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from god_news.operations.models import (
    OperationCommand,
    OperationKind,
    RetentionAction,
    RetentionArtifactKind,
    RetentionCleanupCommand,
    RetentionCleanupReport,
    RetentionItemResult,
    utc_now,
)
from god_news.operations.ports import RetentionAssetProtector

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Candidate:
    path: Path
    root: Path
    artifact_kind: RetentionArtifactKind
    relative_path: str
    modified_at: datetime
    size_bytes: int
    modified_ns: int


class RetentionCleanupHandler:
    """Path-scoped retention handler for generated media and uploaded MP4 files."""

    def __init__(
        self,
        *,
        media_root: Path,
        uploaded_mp4_root: Path,
        media_retention_days: int,
        uploaded_mp4_retention_days: int,
        media_extensions: tuple[str, ...],
        asset_protector: RetentionAssetProtector | None = None,
        asset_lifecycle_lock: asyncio.Lock | None = None,
    ) -> None:
        self._media_root = media_root.expanduser().resolve(strict=False)
        self._uploaded_mp4_root = uploaded_mp4_root.expanduser().resolve(strict=False)
        self._media_retention_days = media_retention_days
        self._uploaded_mp4_retention_days = uploaded_mp4_retention_days
        self._media_extensions = frozenset(suffix.casefold() for suffix in media_extensions)
        self._asset_protector = asset_protector
        self._asset_lifecycle_lock = asset_lifecycle_lock or asyncio.Lock()
        self._lock = asyncio.Lock()

    @property
    def kind(self) -> OperationKind:
        return OperationKind.RETENTION_CLEANUP

    async def execute(self, command: OperationCommand) -> RetentionCleanupReport:
        if not isinstance(command, RetentionCleanupCommand):
            raise TypeError("retention handler received an unsupported command")
        async with self._asset_lifecycle_lock:
            protected_paths = await self._protected_paths()
            async with self._lock:
                worker = asyncio.create_task(
                    asyncio.to_thread(self._execute_sync, command, protected_paths)
                )
                try:
                    return await asyncio.shield(worker)
                except asyncio.CancelledError:
                    # Cancelling an await does not stop its worker thread. Keep
                    # the locks until filesystem mutation has actually ended.
                    await asyncio.shield(worker)
                    raise

    async def _protected_paths(self) -> frozenset[Path]:
        protector = self._asset_protector
        if protector is None:
            return frozenset()
        paths = await protector.protected_asset_paths()
        resolved: set[Path] = set()
        for path in paths:
            try:
                resolved.add(path.expanduser().resolve(strict=False))
            except OSError:
                continue
        return frozenset(resolved)

    def _execute_sync(
        self,
        command: RetentionCleanupCommand,
        protected_paths: frozenset[Path],
    ) -> RetentionCleanupReport:
        started_at = utc_now()
        plans = (
            (
                self._media_root,
                RetentionArtifactKind.MEDIA,
                self._media_extensions,
                started_at - timedelta(days=self._media_retention_days),
            ),
            (
                self._uploaded_mp4_root,
                RetentionArtifactKind.UPLOADED_MP4,
                frozenset({".mp4"}),
                started_at - timedelta(days=self._uploaded_mp4_retention_days),
            ),
        )
        results: list[RetentionItemResult] = []
        for root, artifact_kind, extensions, cutoff in plans:
            candidates, inspection_results = self._scan_root(
                root=root,
                artifact_kind=artifact_kind,
                extensions=extensions,
                cutoff=cutoff,
                protected_paths=protected_paths,
            )
            results.extend(inspection_results)
            results.extend(
                self._apply_candidate(candidate, dry_run=command.dry_run)
                for candidate in candidates
            )

        deleted_count = sum(item.action is RetentionAction.DELETED for item in results)
        eligible_count = sum(
            item.action in {RetentionAction.WOULD_DELETE, RetentionAction.DELETED}
            for item in results
        )
        failed_count = sum(item.action is RetentionAction.FAILED for item in results)
        reclaimed_bytes = sum(
            item.size_bytes for item in results if item.action is RetentionAction.DELETED
        )
        report = RetentionCleanupReport(
            dry_run=command.dry_run,
            started_at=started_at,
            finished_at=utc_now(),
            eligible_count=eligible_count,
            deleted_count=deleted_count,
            failed_count=failed_count,
            reclaimed_bytes=reclaimed_bytes,
            items=results,
        )
        logger.info(
            "retention cleanup finished dry_run=%s eligible=%d deleted=%d failed=%d",
            command.dry_run,
            eligible_count,
            deleted_count,
            failed_count,
        )
        return report

    def _scan_root(
        self,
        *,
        root: Path,
        artifact_kind: RetentionArtifactKind,
        extensions: frozenset[str],
        cutoff: datetime,
        protected_paths: frozenset[Path],
    ) -> tuple[list[_Candidate], list[RetentionItemResult]]:
        if not root.exists():
            return [], []
        if not root.is_dir():
            return [], [
                RetentionItemResult(
                    artifact_kind=artifact_kind,
                    relative_path=".",
                    action=RetentionAction.FAILED,
                    reason="Configured retention root is not a directory.",
                )
            ]

        candidates: list[_Candidate] = []
        results: list[RetentionItemResult] = []
        try:
            paths = sorted(root.rglob("*"), key=lambda path: path.as_posix())
        except OSError:
            return [], [
                RetentionItemResult(
                    artifact_kind=artifact_kind,
                    relative_path=".",
                    action=RetentionAction.FAILED,
                    reason="Retention root could not be enumerated.",
                )
            ]

        for path in paths:
            if path.suffix.casefold() not in extensions:
                continue
            relative_path = path.relative_to(root).as_posix()
            if path.is_symlink():
                results.append(
                    RetentionItemResult(
                        artifact_kind=artifact_kind,
                        relative_path=relative_path,
                        action=RetentionAction.SKIPPED,
                        reason="Symbolic links are never deleted by retention cleanup.",
                    )
                )
                continue
            try:
                resolved = path.resolve(strict=True)
                file_stat = path.stat(follow_symlinks=False)
            except OSError:
                results.append(
                    RetentionItemResult(
                        artifact_kind=artifact_kind,
                        relative_path=relative_path,
                        action=RetentionAction.FAILED,
                        reason="File metadata could not be inspected.",
                    )
                )
                continue
            if not resolved.is_relative_to(root) or not stat.S_ISREG(file_stat.st_mode):
                results.append(
                    RetentionItemResult(
                        artifact_kind=artifact_kind,
                        relative_path=relative_path,
                        action=RetentionAction.SKIPPED,
                        reason="Candidate did not resolve to a regular file inside its root.",
                    )
                )
                continue
            if resolved in protected_paths:
                results.append(
                    RetentionItemResult(
                        artifact_kind=artifact_kind,
                        relative_path=relative_path,
                        modified_at=datetime.fromtimestamp(file_stat.st_mtime, UTC),
                        size_bytes=file_stat.st_size,
                        action=RetentionAction.SKIPPED,
                        reason="Asset is claimed by an active video batch.",
                    )
                )
                continue
            modified_at = datetime.fromtimestamp(file_stat.st_mtime, UTC)
            if modified_at > cutoff:
                continue
            candidates.append(
                _Candidate(
                    path=path,
                    root=root,
                    artifact_kind=artifact_kind,
                    relative_path=relative_path,
                    modified_at=modified_at,
                    size_bytes=file_stat.st_size,
                    modified_ns=file_stat.st_mtime_ns,
                )
            )
        return candidates, results

    @staticmethod
    def _apply_candidate(candidate: _Candidate, *, dry_run: bool) -> RetentionItemResult:
        common = {
            "artifact_kind": candidate.artifact_kind,
            "relative_path": candidate.relative_path,
            "modified_at": candidate.modified_at,
            "size_bytes": candidate.size_bytes,
        }
        if dry_run:
            return RetentionItemResult(action=RetentionAction.WOULD_DELETE, **common)
        try:
            if candidate.path.is_symlink():
                return RetentionItemResult(
                    action=RetentionAction.SKIPPED,
                    reason="Candidate became a symbolic link before deletion.",
                    **common,
                )
            resolved = candidate.path.resolve(strict=True)
            current_stat = candidate.path.stat(follow_symlinks=False)
            if not resolved.is_relative_to(candidate.root) or not stat.S_ISREG(
                current_stat.st_mode
            ):
                return RetentionItemResult(
                    action=RetentionAction.SKIPPED,
                    reason="Candidate left its configured root before deletion.",
                    **common,
                )
            if (
                current_stat.st_size != candidate.size_bytes
                or current_stat.st_mtime_ns != candidate.modified_ns
            ):
                return RetentionItemResult(
                    action=RetentionAction.SKIPPED,
                    reason="Candidate changed after inspection and was not deleted.",
                    **common,
                )
            candidate.path.unlink()
        except FileNotFoundError:
            return RetentionItemResult(
                action=RetentionAction.SKIPPED,
                reason="Candidate no longer exists.",
                **common,
            )
        except OSError:
            return RetentionItemResult(
                action=RetentionAction.FAILED,
                reason="Candidate could not be deleted.",
                **common,
            )
        return RetentionItemResult(action=RetentionAction.DELETED, **common)


class CompositeRetentionAssetProtector:
    """Union multiple durable asset claim sources without coupling repositories."""

    def __init__(self, *protectors: RetentionAssetProtector) -> None:
        self._protectors = protectors

    async def protected_asset_paths(self) -> Sequence[Path]:
        protected: list[Path] = []
        for protector in self._protectors:
            protected.extend(await protector.protected_asset_paths())
        return protected
