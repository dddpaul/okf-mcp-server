"""Per-owner pull-on-demand TTL cache (US-003).

Each owner gets one :class:`OwnerCache` holding its checkout, loaded docs, built
MCP :class:`~mcp.server.Server`, the timestamp of its last pull, and an
``asyncio.Lock``. :meth:`OwnerCache.load` performs the one-time startup clone;
:meth:`OwnerCache.get_or_refresh` serves committed content freshly-enough by
pulling only when the owner is staler than its TTL; :meth:`OwnerCache.force_refresh`
pulls unconditionally for ``POST /{owner}/refresh``.

Every git/scan/build step is blocking, so it runs off the event loop in a worker
thread; the resulting state is swapped in on the loop in one synchronous step so
readers never observe a half-applied refresh. The per-owner lock serializes an
owner's pulls (no concurrent double-pull) while leaving other owners — each with
their own lock and worker thread — completely independent. The TTL clock is
injectable so tests advance time deterministically instead of sleeping.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from mcp.server import Server

from ..config import ServerConfig
from ..server import ParsedDoc, build_server, load_docs
from .git_source import clone_owner, fetch_and_reset, head_commit
from .registry import Credential, ResolvedOwner


@dataclass(frozen=True)
class RefreshResult:
    """Summary of a completed pull, returned by :meth:`OwnerCache.force_refresh`.

    These are exactly the fields the ``POST /{owner}/refresh`` endpoint reports.

    Attributes:
        owner: Owner name that was refreshed.
        ref: Effective branch/tag the owner tracks.
        commit: ``HEAD`` commit SHA served after the pull.
        docs_loaded: Number of exported docs loaded from the refreshed checkout.
    """

    owner: str
    ref: str
    commit: str
    docs_loaded: int


@dataclass(frozen=True)
class _PullOutcome:
    """Result of a blocking clone/pull, applied to the cache back on the loop.

    Attributes:
        checkout: The owner's checkout directory.
        docs: Docs to serve (freshly scanned, or reused when the tree is unchanged).
        server: MCP server to serve (rebuilt only when the tree changed).
        commit: ``HEAD`` commit SHA after the operation.
    """

    checkout: Path
    docs: list[ParsedDoc]
    server: Server
    commit: str


class OwnerCache:
    """Mutable per-owner content cache with TTL-gated pull-on-demand refresh.

    Attributes:
        resolved: The owner's resolved config (url, ref, ttl).
        dest: Checkout directory the owner's repo is cloned into.
        lock: Serializes this owner's pulls so concurrent requests never
            double-pull; independent of every other owner's lock.
        checkout: Checkout path once cloned, else ``None``.
        docs: Currently served docs.
        server: Currently served MCP server, else ``None`` before the first load.
        commit: ``HEAD`` commit SHA currently served, else ``None`` before load.
        last_pulled: Clock reading of the most recent successful pull, else ``None``.
    """

    def __init__(
        self,
        resolved: ResolvedOwner,
        dest: Path,
        *,
        clock: Callable[[], float] = time.monotonic,
        credentials: Mapping[str, Credential] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        """Initialize an unloaded cache for one owner.

        Args:
            resolved: The owner's resolved config.
            dest: Target checkout directory.
            clock: Monotonic-seconds source for TTL staleness; injectable so
                tests advance time deterministically. Defaults to ``time.monotonic``.
            credentials: Per-host git credentials from the registry, injected into
                the clone/fetch URLs per invocation; defaults to none (public repos).
            env: Environment the tokens are read from; defaults to ``os.environ``.
        """
        self.resolved = resolved
        self.dest = dest
        self._clock = clock
        self._credentials = credentials or {}
        self._env = env
        self.lock = asyncio.Lock()
        self.checkout: Path | None = None
        self.docs: list[ParsedDoc] = []
        self.server: Server | None = None
        self.commit: str | None = None
        self.last_pulled: float | None = None

    async def load(self) -> None:
        """Perform the one-time startup clone and initial build (off the loop).

        Runs the shallow clone, doc scan, and server build in a worker thread,
        then applies the result on the loop. Call exactly once per owner before
        any :meth:`get_or_refresh` / :meth:`force_refresh`.
        """
        outcome = await asyncio.to_thread(self._clone_blocking)
        self._apply(outcome)

    async def get_or_refresh(self, ttl: float) -> Server:
        """Return the owner's server, pulling first only if staler than ``ttl``.

        A fresh owner (pulled less than ``ttl`` ago) is served without any git
        work. When stale, the pull runs under the owner's lock with a re-check,
        so concurrent stale requests trigger a single pull; the docs and server
        are rebuilt only if the pull actually moved ``HEAD``.

        Args:
            ttl: Freshness window in seconds; the owner is re-pulled once its
                last pull is at least ``ttl`` seconds old.

        Returns:
            The MCP server serving the owner's current (freshly-enough) content.
        """
        if self._is_fresh(ttl):
            assert self.server is not None  # freshness implies a completed load
            return self.server
        async with self.lock:
            if self._is_fresh(ttl):  # another request refreshed while we waited
                assert self.server is not None
                return self.server
            outcome = await asyncio.to_thread(self._pull_blocking)
            self._apply(outcome)
            assert self.server is not None
            return self.server

    async def force_refresh(self) -> RefreshResult:
        """Pull unconditionally, ignoring TTL, and summarize the result.

        Backs ``POST /{owner}/refresh`` (and later a git webhook). Serialized by
        the owner's lock like :meth:`get_or_refresh`, so it never races an
        in-flight TTL pull into a double-pull.

        Returns:
            A :class:`RefreshResult` naming the owner, ref, served commit, and
            number of docs loaded.
        """
        async with self.lock:
            outcome = await asyncio.to_thread(self._pull_blocking)
            self._apply(outcome)
            return RefreshResult(
                owner=self.resolved.owner,
                ref=self.resolved.ref,
                commit=outcome.commit,
                docs_loaded=len(outcome.docs),
            )

    def _is_fresh(self, ttl: float) -> bool:
        """Report whether the owner was pulled within the last ``ttl`` seconds."""
        return (
            self.server is not None
            and self.last_pulled is not None
            and (self._clock() - self.last_pulled) < ttl
        )

    def _clone_blocking(self) -> _PullOutcome:
        """Shallow-clone the owner and build its server (runs in a worker thread)."""
        checkout = clone_owner(
            self.resolved.url,
            self.resolved.ref,
            self.dest,
            credentials=self._credentials,
            env=self._env,
        )
        docs = self._scan_docs(checkout)
        return _PullOutcome(
            checkout=checkout,
            docs=docs,
            server=build_server(docs),
            commit=head_commit(checkout),
        )

    def _pull_blocking(self) -> _PullOutcome:
        """Fetch+reset the checkout and rebuild only on a moved HEAD (worker thread).

        Reads the current ``checkout``/``commit``/``docs``/``server`` — all
        mutated only by :meth:`_apply` on the loop and never while this owner's
        lock is held — so the snapshot is stable for the duration of the pull.
        """
        checkout = self.checkout
        assert checkout is not None  # load() ran first; app gates on readiness
        before = self.commit
        fetch_and_reset(
            checkout,
            self.resolved.ref,
            self.resolved.url,
            credentials=self._credentials,
            env=self._env,
        )
        after = head_commit(checkout)
        if after == before and self.server is not None:
            # Unchanged tree: reuse the built docs/server, skip load+build cost.
            return _PullOutcome(checkout, self.docs, self.server, after)
        docs = self._scan_docs(checkout)
        return _PullOutcome(checkout, docs, build_server(docs), after)

    def _scan_docs(self, checkout: Path) -> list[ParsedDoc]:
        """Reuse the stdio ``load_docs`` verbatim against the owner's checkout."""
        config = ServerConfig(owner=self.resolved.owner, roots=(checkout,))
        return load_docs(config)

    def _apply(self, outcome: _PullOutcome) -> None:
        """Swap in a pull's result on the loop in one step and stamp last_pulled."""
        self.checkout = outcome.checkout
        self.docs = outcome.docs
        self.server = outcome.server
        self.commit = outcome.commit
        self.last_pulled = self._clock()


__all__ = ["OwnerCache", "RefreshResult"]
