"""URL builders for Connhex deployments.

By default, SDK clients target the Connhex SaaS instance at
``https://connhex.com``. Custom, staging, private, or self-hosted deployments
can provide their own instance URL.

A Connhex instance is served from a single root domain (the "instance URL").
Each Connhex subsystem lives on a dedicated subdomain of that root: the public
APIs on ``apis.<host>``, the identity / account flows on ``accounts.<host>``,
and so on. The helpers in this module take an instance URL and return the
right per-subsystem URL.

Most users of the SDK never need to call these — :class:`AsyncConnhex`
handles URL construction internally. They are exposed publicly for code
that lives next to the SDK and needs to talk to the same deployment outside
the standard request path, for example:

- building a browser redirect to the accounts portal (login, password
  reset, OAuth consent),
- assembling webhook callback URLs that point back at the same instance,
- driving custom auth flows that hit ``accounts.<host>`` directly.

All helpers accept an ``instance_url`` with an explicit scheme and host
(trailing slashes are tolerated) and raise :class:`ValueError` on malformed
input. ``DEFAULT_INSTANCE_URL`` exposes the SDK's default SaaS root. The
helpers are pure functions — no network calls, no caching.

Example:

    >>> build_apis_url("https://connhex.com/")
    'https://apis.connhex.com'
    >>> build_accounts_url("https://connhex.com")
    'https://accounts.connhex.com'
    >>> build_url("https://connhex.com", "apis")
    'https://apis.connhex.com'
"""

from urllib.parse import urlsplit

DEFAULT_INSTANCE_URL = "https://connhex.com"


def _parts(instance_url: str) -> tuple[str, str]:
    parts = urlsplit(instance_url.rstrip("/"))
    if not parts.scheme or not parts.hostname:
        raise ValueError(f"invalid instance_url: {instance_url!r}")
    return parts.scheme, parts.hostname


def build_apis_url(instance_url: str) -> str:
    """Return the ``apis.<host>`` URL for a Connhex instance.

    This is the base URL for every Connhex REST API call. Combine it with
    a service path (e.g. ``/things/v1/...``) to address a specific
    endpoint. :class:`AsyncConnhex` uses this internally; reach for it
    directly only when issuing requests outside the SDK's request path.
    """
    scheme, host = _parts(instance_url)
    return f"{scheme}://apis.{host}"


def build_accounts_url(instance_url: str) -> str:
    """Return the ``accounts.<host>`` URL for a Connhex instance.

    This is where identity and auth flows live: login, password reset,
    OAuth authorization, and session management. Use it to
    build browser redirects or to drive custom auth flows that the SDK's
    bearer-token model does not cover.
    """
    scheme, host = _parts(instance_url)
    return f"{scheme}://accounts.{host}"


def build_url(instance_url: str, subsystem: str) -> str:
    """Return the URL for a named Connhex subsystem.

    ``subsystem`` selects the target: ``"apis"`` resolves to
    :func:`build_apis_url`, ``"accounts"`` to :func:`build_accounts_url`.
    Unknown values raise :class:`ValueError`.

    Prefer the named helpers in new code; ``build_url`` exists for call
    sites that pick the subsystem dynamically (e.g. configuration-driven
    routing).
    """
    if subsystem == "apis":
        return build_apis_url(instance_url)
    if subsystem == "accounts":
        return build_accounts_url(instance_url)
    raise ValueError(f"unknown subsystem {subsystem!r}")
