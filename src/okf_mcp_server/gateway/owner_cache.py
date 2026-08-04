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
from subprocess import CalledProcessError

from mcp.server import Server

from ..config import ServerConfig
from ..server import ParsedDoc, build_server, load_docs
from .git_source import CredentialError, clone_owner, fetch_and_reset, head_commit
from .registry import Credential, ResolvedOwner

# A git-source failure that the offline fallback treats as "source unavailable":
# a git subprocess non-zero exit (host unreachable, ref gone) or a missing south
# credential (can't-authenticate is the same degraded state as can't-reach). A
# healthy checkout degrades to stale-but-served on these; an empty volume fails.
_SOURCE_UNAVAILABLE = (CalledProcessError, CredentialError)


class RefreshUnavailable(RuntimeError):
    """Raised by :meth:`force_refresh` when a pull fails but the owner keeps serving.

    An explicit ``POST /{owner}/refresh`` must report a source outage loudly (so a
    ``curl --fail`` script trips) even though the owner keeps serving its last-good
    checkout. This carries the still-served commit and a token-free error string so
    the route can answer ``502 Bad Gateway`` without breaking the content path.

    Attributes:
        served_commit: ``HEAD`` SHA still being served, or ``None`` if never loaded.
        error: Token-free description of the git-source failure.
    """

    def __init__(self, *, served_commit: str | None, error: str) -> None:
        super().__init__(error)
        self.served_commit = served_commit
        self.error = error


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
        last_pulled_wall: Wall-clock (epoch seconds) of the most recent successful
            pull, rendered as ``last_pulled_at`` by ``GET /status``, else ``None``;
            kept separate from the monotonic ``last_pulled`` so TTL stays jump-immune.
        source_available: Whether the most recent git attempt (clone/fetch)
            succeeded; ``False`` marks the served content as a stale offline
            fallback. Starts ``True`` (optimistic — no attempt has failed yet).
        last_pull_attempt_at: Wall-clock (epoch seconds) of the most recent pull
            *attempt*, success or failure, else ``None`` before the first attempt;
            rendered as ``last_pull_attempt_at`` by ``GET /status``. Distinct from
            ``last_pulled_wall`` (age of served *content*) so "serving old docs,
            still retrying" is distinguishable from "haven't retried since boot".
        last_pull_error: Token-free description of the most recent failed attempt,
            else ``None`` when the last attempt succeeded (or none has run yet).
    """

    def __init__(
        self,
        resolved: ResolvedOwner,
        dest: Path,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        credentials: Mapping[str, Credential] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        """Initialize an unloaded cache for one owner.

        Args:
            resolved: The owner's resolved config.
            dest: Target checkout directory.
            clock: Monotonic-seconds source for TTL staleness; injectable so
                tests advance time deterministically. Defaults to ``time.monotonic``.
            wall_clock: Absolute wall-clock (epoch seconds) source stamped at each
                pull for display as ``last_pulled_at``; separate from ``clock`` so
                TTL stays monotonic (jump-immune) while humans get an absolute time.
                Injectable for deterministic tests. Defaults to ``time.time``.
            credentials: Per-host git credentials from the registry, injected into
                the clone/fetch URLs per invocation; defaults to none (public repos).
            env: Environment the tokens are read from; defaults to ``os.environ``.
        """
        self.resolved = resolved
        self.dest = dest
        self._clock = clock
        self._wall_clock = wall_clock
        self._credentials = credentials or {}
        self._env = env
        self.lock = asyncio.Lock()
        self.checkout: Path | None = None
        self.docs: list[ParsedDoc] = []
        self.server: Server | None = None
        self.commit: str | None = None
        self.last_pulled: float | None = None
        self.last_pulled_wall: float | None = None
        self.source_available: bool = True
        self.last_pull_attempt_at: float | None = None
        self.last_pull_error: str | None = None

    async def load(self) -> None:
        """Serve the owner at startup, preferring last-good content over empty failure.

        The persisted volume checkout is an authoritative offline fallback: a
        source outage degrades to *stale-but-served*, never *empty-and-failed*.
        The branch table (integrity gate = ``git rev-parse HEAD``; source =
        clone/fetch):

        =================  =================  =============================
        Volume state       Source reachable?  Outcome
        =================  =================  =============================
        Healthy checkout   up                 fetch+reset, serve fresh
        Healthy checkout   down               serve existing (stale, no raise)
        Corrupt            up                 rmtree, fresh clone
        Corrupt            down               rmtree, clone fails -> failed
        Absent             up                 fresh clone
        Absent             down               clone fails -> failed
        =================  =================  =============================

        A healthy checkout is **never** ``rmtree``'d — only an absent or corrupt
        one is discarded and re-cloned (``clone_owner`` owns that removal). A
        source outage (git failure or missing south credential) with a healthy
        checkout serves the existing checkout as-is; only an empty/corrupt volume
        with the source down fails the owner. Every git/scan/build step runs in a
        worker thread; the result is applied on the loop. Call exactly once per
        owner before any :meth:`get_or_refresh` / :meth:`force_refresh`.
        """
        if self._valid_checkout_exists(self.dest):
            # Healthy last-good checkout: refresh it in place, but never discard it.
            self.checkout = self.dest  # let _pull_blocking fetch into the existing tree
            try:
                outcome = await asyncio.to_thread(self._pull_blocking)
            except _SOURCE_UNAVAILABLE as exc:
                outcome = await asyncio.to_thread(self._serve_existing)
                self._apply(outcome, source_available=False, last_pull_error=str(exc))
            else:
                self._apply(outcome, source_available=True, last_pull_error=None)
            return
        # Absent or corrupt: a fresh clone is the only servable option (clone_owner
        # rmtree's a corrupt dir first). A source outage here has nothing to fall
        # back to, so the failure is stamped and re-raised into the failed state.
        try:
            outcome = await asyncio.to_thread(self._clone_blocking)
        except _SOURCE_UNAVAILABLE as exc:
            self._stamp_attempt(source_available=False, error=str(exc))
            raise
        self._apply(outcome, source_available=True, last_pull_error=None)

    async def get_or_refresh(self, ttl: float) -> Server:
        """Return the owner's server, pulling first only if staler than ``ttl``.

        A fresh owner (pulled less than ``ttl`` ago) is served without any git
        work. When stale, the pull runs under the owner's lock with a re-check,
        so concurrent stale requests trigger a single pull; the docs and server
        are rebuilt only if the pull actually moved ``HEAD``.

        A source outage during a TTL pull never breaks the request: the failed
        attempt is stamped and the existing (now stale) server is served instead
        of raising. Because a failed attempt does not advance the success clock,
        the owner stays past-TTL and every later request re-attempts the pull, so
        it self-heals the instant the source returns.

        Args:
            ttl: Freshness window in seconds; the owner is re-pulled once its
                last pull is at least ``ttl`` seconds old.

        Returns:
            The MCP server serving the owner's current (freshly-enough, or stale
            offline-fallback) content.
        """
        if self._is_fresh(ttl):
            assert self.server is not None  # freshness implies a completed load
            return self.server
        async with self.lock:
            if self._is_fresh(ttl):  # another request refreshed while we waited
                assert self.server is not None
                return self.server
            try:
                outcome = await asyncio.to_thread(self._pull_blocking)
            except _SOURCE_UNAVAILABLE as exc:
                # Source down mid-serve: keep serving the last-good build, record
                # the failed attempt, and stay past-TTL so the next request retries.
                self._stamp_attempt(source_available=False, error=str(exc))
                assert self.server is not None  # load() established a served server
                return self.server
            self._apply(outcome, source_available=True, last_pull_error=None)
            assert self.server is not None
            return self.server

    async def force_refresh(self) -> RefreshResult:
        """Pull unconditionally, ignoring TTL, and summarize the result.

        Backs ``POST /{owner}/refresh`` (and later a git webhook). Serialized by
        the owner's lock like :meth:`get_or_refresh`, so it never races an
        in-flight TTL pull into a double-pull.

        Unlike :meth:`get_or_refresh`, an explicit refresh reports a source outage
        loudly: the failed attempt is stamped and the owner keeps serving its
        last-good build, but a :class:`RefreshUnavailable` is raised so the route
        can answer ``502``. The content path is untouched, so MCP requests for the
        owner continue to succeed.

        Returns:
            A :class:`RefreshResult` naming the owner, ref, served commit, and
            number of docs loaded.

        Raises:
            RefreshUnavailable: If the git source is unreachable or its south
                credential is unset; the owner keeps serving its last-good commit.
        """
        async with self.lock:
            try:
                outcome = await asyncio.to_thread(self._pull_blocking)
            except _SOURCE_UNAVAILABLE as exc:
                self._stamp_attempt(source_available=False, error=str(exc))
                raise RefreshUnavailable(
                    served_commit=self.commit, error=str(exc)
                ) from exc
            self._apply(outcome, source_available=True, last_pull_error=None)
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

    def _valid_checkout_exists(self, dest: Path) -> bool:
        """Report whether ``dest`` holds a git checkout with a resolvable ``HEAD``.

        The integrity gate for the offline fallback: a directory that exists and
        whose ``git rev-parse HEAD`` succeeds is servable last-good content and is
        never discarded; an absent or corrupt checkout (missing ``.git``,
        unresolvable ``HEAD``) has no fallback value and is re-cloned instead.

        Args:
            dest: The owner's checkout directory to probe.

        Returns:
            ``True`` if ``dest`` is a git checkout with a resolvable ``HEAD``.
        """
        if not dest.exists():
            return False
        try:
            head_commit(dest)
        except CalledProcessError:
            return False
        return True

    def _serve_existing(self) -> _PullOutcome:
        """Build a server from the on-disk checkout without contacting the source.

        The offline-fallback counterpart of :meth:`_pull_blocking`'s unchanged-tree
        branch: scans the current checkout and builds a server from its present
        ``HEAD``, so a source outage keeps serving the last-good content already in
        the volume. Only called after :meth:`_valid_checkout_exists` confirmed
        ``HEAD`` resolves, so ``head_commit`` here cannot fail.
        """
        checkout = self.dest
        docs = self._scan_docs(checkout)
        return _PullOutcome(
            checkout=checkout,
            docs=docs,
            server=build_server(docs),
            commit=head_commit(checkout),
        )

    def _scan_docs(self, checkout: Path) -> list[ParsedDoc]:
        """Reuse the stdio ``load_docs`` verbatim against the owner's checkout."""
        config = ServerConfig(owner=self.resolved.owner, roots=(checkout,))
        return load_docs(config)

    def _apply(
        self,
        outcome: _PullOutcome,
        *,
        source_available: bool,
        last_pull_error: str | None,
    ) -> None:
        """Swap in a pull/serve result on the loop and stamp the attempt clocks.

        Always records the attempt (``source_available``, ``last_pull_attempt_at``,
        ``last_pull_error``). The success clocks (``last_pulled`` /
        ``last_pulled_wall``, which gate TTL freshness and render ``last_pulled_at``)
        are stamped **only** when ``source_available`` is true: a stale offline
        fallback swaps in on-disk content without claiming a fresh pull, so it stays
        past-TTL and keeps re-attempting until the source returns.

        Args:
            outcome: The clone/pull/serve result to serve.
            source_available: Whether this outcome came from a successful git pull
                (true) or an offline fallback to the existing checkout (false).
            last_pull_error: Token-free error to record, or ``None`` on success.
        """
        self.checkout = outcome.checkout
        self.docs = outcome.docs
        self.server = outcome.server
        self.commit = outcome.commit
        self._stamp_attempt(source_available=source_available, error=last_pull_error)
        if source_available:
            self.last_pulled = self._clock()
            self.last_pulled_wall = self._wall_clock()

    def _stamp_attempt(self, *, source_available: bool, error: str | None) -> None:
        """Record a pull attempt's outcome without swapping the served content.

        Used when a refresh fails while a good server is already being served: the
        served content and its ``last_pulled`` success clock are left intact so the
        owner keeps answering, while ``source_available`` / ``last_pull_attempt_at``
        / ``last_pull_error`` reflect the failed attempt (and the unchanged success
        clock keeps the owner past-TTL, so the next request re-attempts).

        Args:
            source_available: Whether the just-finished attempt reached the source.
            error: Token-free error string for a failed attempt, else ``None``.
        """
        self.source_available = source_available
        self.last_pull_attempt_at = self._wall_clock()
        self.last_pull_error = error


__all__ = ["OwnerCache", "RefreshResult", "RefreshUnavailable"]
