"""Configuration validation that enforces principles 3 and 8 at load time."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


class ConfigError(ValueError):
    pass


_STAGING_MARKERS = ("staging", "stg", "sandbox", "test", "dev", "qa", "preprod", "uat")
_LOOPBACK = ("localhost", "127.0.0.1", "::1")
_HOST = re.compile(r"[a-z0-9._\-]+|::1")
_PROD_CREDENTIAL = re.compile(r"(^|[_\-])(prod|production|live)([_\-]|$)", re.IGNORECASE)


@dataclass(frozen=True)
class TargetConfig:
    """Where the staging target is and how to authenticate. Never production."""

    base_url: str
    token: str

    def __post_init__(self) -> None:
        # What is validated here must be exactly what the transport dials: one scheme, one
        # ASCII host, no userinfo, nothing after the path.
        try:
            parts = urlsplit(self.base_url)
            host = (parts.hostname or "").lower()
            _ = parts.port  # a malformed or out-of-range port raises here, not at dial time
        except ValueError as e:
            raise ConfigError(f"base_url {self.base_url!r} is not a valid URL: {e}") from e
        if parts.scheme not in ("http", "https"):
            raise ConfigError(f"base_url scheme {parts.scheme!r} is not http or https")
        if "@" in parts.netloc:
            raise ConfigError("base_url must not carry userinfo (user:password@host)")
        if "?" in self.base_url or "#" in self.base_url:
            raise ConfigError("base_url must not carry a query or fragment")
        if not host:
            raise ConfigError(f"base_url {self.base_url!r} has no host")
        if not _HOST.fullmatch(host):
            raise ConfigError(
                f"host {host!r} is not a plain ASCII host name; write an internationalised "
                "name in its punycode form so the name reviewed is the name dialled"
            )
        if any(c.isspace() or not c.isprintable() for c in self.base_url):
            raise ConfigError("base_url must not contain whitespace or control characters")
        loopback = host in _LOOPBACK
        labels = re.split(r"[.\-_]", host)
        if not loopback and not any(m in labels for m in _STAGING_MARKERS):
            raise ConfigError(
                f"host {host!r} is not recognisably staging; expected a label such as "
                f"{', '.join(_STAGING_MARKERS)} (principle 8: staging only)"
            )
        if any(_PROD_CREDENTIAL.search(label) for label in labels) or any(
            label in ("prod", "production", "live") for label in labels
        ):
            raise ConfigError(f"host {host!r} carries a production label (principle 8)")
        if parts.scheme != "https" and not loopback:
            raise ConfigError("base_url must use https unless it is loopback")
        if not self.token or any(c.isspace() or not c.isprintable() for c in self.token):
            raise ConfigError("token is empty or contains whitespace or control characters")
        if _PROD_CREDENTIAL.search(self.token):
            raise ConfigError("credential looks like production (principle 8)")


@dataclass(frozen=True)
class ModelPolicy:
    """Judge and actor are different model families; judge differs from a known target family."""

    actor_family: str
    judge_family: str
    target_family: str | None

    @staticmethod
    def _norm(s: str) -> str:
        return s.strip().lower()

    def __post_init__(self) -> None:
        actor, judge = self._norm(self.actor_family), self._norm(self.judge_family)
        if actor == judge:
            raise ConfigError(f"judge and actor share model family {judge!r} (principle 3)")
        if self.target_family is not None and self._norm(self.target_family) == judge:
            raise ConfigError(f"judge and target share model family {judge!r} (principle 3)")

    @property
    def target_family_known(self) -> bool:
        return self.target_family is not None
