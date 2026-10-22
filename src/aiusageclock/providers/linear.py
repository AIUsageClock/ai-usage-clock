from __future__ import annotations

import logging
import re
from typing import Any, Callable

import requests

from ..config import Config, get_linear_key
from ..models import SnapshotStatus, UsageMetric, UsageSnapshot
from .base import Provider

LINEAR_API = "https://api.linear.app/graphql"

log = logging.getLogger("aiusageclock.providers.linear")

QUERY = """
query AiUsageClockLinear {
  organization {
    subscription { type }
  }
  teams {
    nodes {
      issueCount
    }
  }
}
""".strip()

_MAX_ERROR_LEN = 200
_MSG_AUTH = "Linear rejected the API key. Update it in Settings."
_MSG_MISSING_KEY = "Add a Linear API key in Settings."
_MSG_INVALID_KEY = (
    "The saved Linear API key contains invalid characters. Update it in Settings."
)


class _LinearError(Exception):
    """A classified Linear failure that maps to SnapshotStatus.ERROR."""


class _LinearAuthError(_LinearError):
    """A classified Linear failure that maps to SnapshotStatus.AUTH_REQUIRED."""


def _is_auth_error(error: object) -> bool:
    if not isinstance(error, dict):
        return False
    extensions = error.get("extensions")
    if not isinstance(extensions, dict):
        return False
    code = extensions.get("code")
    if isinstance(code, str) and code.upper() == "AUTHENTICATION_ERROR":
        return True
    kind = extensions.get("type")
    return isinstance(kind, str) and "authentication" in kind.lower()


def _truncate(text: str) -> str:
    return text[:_MAX_ERROR_LEN]


def _api_error_message(errors: object, status: int | None = None) -> str:
    """Describe a GraphQL ``errors`` array; ``status`` is the HTTP status.

    A non-2xx ``status`` is included in the text so the user can tell a rate
    limit (HTTP 400 with a RATELIMITED error) from a plain server failure.
    """
    http_error = status is not None and not 200 <= status < 300
    prefix = f"Linear API error (HTTP {status})" if http_error else "Linear API error"
    message: object = None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        message = errors[0].get("message")
    if not isinstance(message, str) or not message.strip():
        return f"{prefix}."
    return _truncate(f"{prefix}: {message.strip()}")


def _fetch(api_key: str) -> dict[str, Any]:
    """POST the GraphQL query and return the validated ``data`` object.

    Raises _LinearAuthError / _LinearError for classified failures. The API key
    only ever travels in the Authorization header: it is never logged and never
    placed in an error string.
    """
    # Personal keys are printable ASCII without whitespace. A non-ASCII value
    # would make http.client raise a UnicodeEncodeError whose message echoes the
    # key's characters, and control characters such as a newline would make it
    # reject the Authorization header value.
    if not re.fullmatch(r"[!-~]+", api_key):
        log.warning(
            "provider api diagnosis provider=linear classification=invalid_key_format"
        )
        raise _LinearAuthError(_MSG_INVALID_KEY)
    try:
        response = requests.post(
            LINEAR_API,
            json={"query": QUERY},
            # Personal API keys are sent as-is, without a "Bearer " prefix.
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            timeout=15,
        )
    except requests.RequestException as exc:
        log.warning(
            "provider api diagnosis provider=linear "
            "classification=request_failed type=%s",
            type(exc).__name__,
        )
        raise _LinearError(
            f"Linear request failed: {type(exc).__name__}"
        ) from None

    status = response.status_code
    try:
        body: object = response.json()
    except ValueError:
        body = None

    errors = body.get("errors") if isinstance(body, dict) else None
    keys = sorted(body) if isinstance(body, dict) else None

    def classify(name: str) -> None:
        log.log(
            logging.DEBUG if name == "usage_ok" else logging.WARNING,
            "provider api diagnosis provider=linear "
            "classification=%s status=%s payload_keys=%s",
            name,
            status,
            keys,
        )

    if isinstance(errors, list) and any(_is_auth_error(e) for e in errors):
        classify("auth_error")
        raise _LinearAuthError(_MSG_AUTH)
    if status == 401:
        classify("http_401")
        raise _LinearAuthError(_MSG_AUTH)
    if errors:
        # Prefer the server's reason (e.g. RATELIMITED) over a bare status code.
        classify("graphql_error")
        raise _LinearError(_api_error_message(errors, status))
    if not 200 <= status < 300:
        classify("http_error")
        raise _LinearError(f"Linear API returned HTTP {status}.")
    if not isinstance(body, dict):
        classify("unexpected_response")
        raise _LinearError("Linear returned an unexpected response.")
    data = body.get("data")
    if not isinstance(data, dict):
        classify("missing_data")
        raise _LinearError("Linear response is missing data.")
    classify("usage_ok")
    return data


def _extract_issue_count(data: dict[str, Any]) -> int:
    """Sum ``issueCount`` over all teams.

    Counts exclude archived issues, matching Linear's Free plan limit; switch
    the source here (e.g. ``organization.createdIssueCount``, which must then
    also be added back to QUERY) if needed. Only teams visible to the key are
    counted, so a key limited to some teams undercounts.
    """
    teams = data.get("teams")
    nodes = teams.get("nodes") if isinstance(teams, dict) else None
    if not isinstance(nodes, list):
        raise ValueError("Linear response is missing team issue counts.")
    total = 0
    for node in nodes:
        count = node.get("issueCount") if isinstance(node, dict) else None
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("Linear returned an invalid issue count.")
        total += count
    return total


def _build_snapshot(payload: dict[str, Any], *, issue_limit: int) -> UsageSnapshot:
    """Build a snapshot from the GraphQL ``data`` object (pure, no network)."""
    organization = payload.get("organization")
    if not isinstance(organization, dict):
        raise ValueError("Linear response is missing organization data.")
    if "subscription" not in organization:
        raise ValueError("Linear response is missing subscription data.")
    subscription = organization["subscription"]
    if subscription is not None and not isinstance(subscription, dict):
        raise ValueError("Linear returned invalid subscription data.")

    if subscription is None:
        if issue_limit < 1:
            raise ValueError("Linear issue limit must be at least 1.")
        count = _extract_issue_count(payload)
        metric = UsageMetric(
            label="Issues",
            percent_used=count * 100 / issue_limit,
            resets_at=None,
            window=None,
            reset_label=f"{count} / {issue_limit}",
            note=f"{count} / {issue_limit} issues (Free plan)",
        )
    else:
        metric = UsageMetric(
            label="Issues",
            percent_used=None,
            resets_at=None,
            window=None,
            reset_label="no limit",
            note="Paid plan: no issue limit",
        )
    return UsageSnapshot(
        provider="linear",
        status=SnapshotStatus.OK,
        metrics=[metric],
    )


class LinearProvider(Provider):
    name = "linear"
    display_name = "Linear"

    def __init__(self, config: Config, pool=None):
        self._config = config
        self._pool = pool

    def refresh(self, on_done: Callable[[UsageSnapshot], None]) -> None:
        api_key = (get_linear_key() or "").strip()
        if not api_key:
            on_done(
                UsageSnapshot(
                    provider=self.name,
                    status=SnapshotStatus.AUTH_REQUIRED,
                    error=_MSG_MISSING_KEY,
                )
            )
            return

        # Read at refresh time so a changed limit applies without a restart.
        issue_limit = self._config.linear.issue_limit

        def work() -> UsageSnapshot:
            try:
                return _build_snapshot(_fetch(api_key), issue_limit=issue_limit)
            except _LinearAuthError as exc:
                return UsageSnapshot(
                    provider=self.name,
                    status=SnapshotStatus.AUTH_REQUIRED,
                    error=str(exc),
                )
            except _LinearError as exc:
                return UsageSnapshot(
                    provider=self.name,
                    status=SnapshotStatus.ERROR,
                    error=str(exc),
                )
            except (TypeError, ValueError) as exc:
                log.warning(
                    "provider api diagnosis provider=linear "
                    "classification=unexpected_response error=%s",
                    exc,
                )
                return UsageSnapshot(
                    provider=self.name,
                    status=SnapshotStatus.ERROR,
                    error=str(exc),
                )

        self._run_async(work, on_done)
