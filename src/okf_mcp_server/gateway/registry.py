"""Parse and validate the multi-owner gateway registry (``servers.yaml``, US-002).

``servers.yaml`` is the authoritative owner allowlist. It has three sections::

    defaults:                 # applied to any owner that omits ref/ttl
      ref: main
      ttl: 60
    owners:
      acme:
        url: file:///srv/acme.git
      beta:
        url: https://bitbucket.corp/beta.git
        ref: release          # optional; overrides defaults.ref
        ttl: 120              # optional; overrides defaults.ttl
    credentials:              # per git host; consumed by the auth task (US-004)
      bitbucket.corp:
        token_env: OKF_GIT_TOKEN_BITBUCKET
        token_user: x-token-auth

The set of registered ``owners`` is the north allowlist: a request for an owner
absent from this file is rejected (404). Only parsing and validation of the
``credentials`` section lands here; resolving credentials into authenticated
clone URLs arrives with US-004.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_REF = "main"
DEFAULT_TTL = 60


class RegistryError(ValueError):
    """Raised when ``servers.yaml`` is missing, malformed, or fails validation.

    The message is written for an operator: it names the offending file and says
    what to fix, so a bad registry fails fast at startup with actionable output.
    """


class Defaults(BaseModel):
    """Fallback ``ref``/``ttl`` applied to any owner that omits them.

    Attributes:
        ref: Branch or tag checked out when an owner does not set its own ``ref``.
        ttl: Refresh TTL in seconds applied when an owner omits its own ``ttl``.
    """

    model_config = ConfigDict(extra="forbid")

    ref: str = DEFAULT_REF
    ttl: int = Field(default=DEFAULT_TTL, gt=0)


class OwnerSpec(BaseModel):
    """A single owner entry in ``servers.yaml``.

    Attributes:
        url: Git URL shallow-cloned to source the owner's docs.
        ref: Optional branch/tag override; falls back to ``defaults.ref``.
        ttl: Optional refresh-TTL override in seconds; falls back to ``defaults.ttl``.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    ref: str | None = None
    ttl: int | None = Field(default=None, gt=0)


class Credential(BaseModel):
    """Per-host git credential (parsed here; consumed by the auth task, US-004).

    Attributes:
        token_env: Environment variable holding the host's read-only access token.
        token_user: Provider-fixed username paired with the token in the clone URL
            (e.g. ``x-token-auth`` for Bitbucket, ``x-access-token`` for GitHub).
    """

    model_config = ConfigDict(extra="forbid")

    token_env: str
    token_user: str


@dataclass(frozen=True)
class ResolvedOwner:
    """An owner with ``ref``/``ttl`` resolved against the ``defaults`` block.

    Attributes:
        owner: Owner name (the ``/{owner}/mcp`` path segment and URI owner).
        url: Git URL to clone.
        ref: Effective branch/tag (owner override or default).
        ttl: Effective refresh TTL in seconds (owner override or default).
    """

    owner: str
    url: str
    ref: str
    ttl: int


class Registry(BaseModel):
    """The validated ``servers.yaml`` document.

    Attributes:
        defaults: Fallback ``ref``/``ttl`` for owners that omit them.
        owners: Registered owners keyed by name; this set is the allowlist.
        credentials: Per-host git credentials keyed by host (consumed in US-004).
    """

    model_config = ConfigDict(extra="forbid")

    defaults: Defaults = Field(default_factory=Defaults)
    owners: dict[str, OwnerSpec]
    credentials: dict[str, Credential] = Field(default_factory=dict)

    def resolve(self, owner: str) -> ResolvedOwner | None:
        """Resolve one owner's effective config, merging the ``defaults`` block.

        Args:
            owner: Owner name to look up.

        Returns:
            The :class:`ResolvedOwner`, or ``None`` if ``owner`` is unregistered.
        """
        spec = self.owners.get(owner)
        if spec is None:
            return None
        return ResolvedOwner(
            owner=owner,
            url=spec.url,
            ref=spec.ref if spec.ref is not None else self.defaults.ref,
            ttl=spec.ttl if spec.ttl is not None else self.defaults.ttl,
        )


def load_registry(path: Path) -> Registry:
    """Load and validate a ``servers.yaml`` registry, failing fast on any error.

    Args:
        path: Filesystem path to ``servers.yaml``.

    Returns:
        The validated :class:`Registry`.

    Raises:
        RegistryError: If the file is missing, unreadable, not valid YAML, not a
            mapping, empty, declares no owners, or violates the schema. The
            message names ``path`` and what to fix.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RegistryError(
            f"servers.yaml not found at {path}; create it with an 'owners:' "
            f"section or set OKF_GATEWAY_SERVERS to its location"
        ) from exc
    except OSError as exc:
        raise RegistryError(f"cannot read servers.yaml at {path}: {exc}") from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise RegistryError(f"servers.yaml at {path} is not valid YAML: {exc}") from exc

    if data is None:
        raise RegistryError(
            f"servers.yaml at {path} is empty; expected an 'owners:' section"
        )
    if not isinstance(data, dict):
        raise RegistryError(
            f"servers.yaml at {path} must be a YAML mapping with an 'owners:' "
            f"section, got {type(data).__name__}"
        )

    try:
        registry = Registry.model_validate(data)
    except ValidationError as exc:
        raise RegistryError(
            f"servers.yaml at {path} failed validation:\n{exc}"
        ) from exc

    if not registry.owners:
        raise RegistryError(
            f"servers.yaml at {path} declares no owners; add at least one entry "
            f"under 'owners:'"
        )
    return registry


__all__ = [
    "DEFAULT_REF",
    "DEFAULT_TTL",
    "Credential",
    "Defaults",
    "OwnerSpec",
    "Registry",
    "RegistryError",
    "ResolvedOwner",
    "load_registry",
]
