"""The guardrail adapters allow only on a complete, clean screen, and fail closed otherwise.

**Model Armor** (``adapters/gcp/model_armor_guardrail.py``) calls the REST API, so the
verdict is read from the JSON form of the sanitize response. It allows ONLY when
``sanitizationResult.filterMatchState`` is ``NO_MATCH_FOUND`` AND
``sanitizationResult.invocationResult`` is ``SUCCESS``. The mapping it replaced allowed on
anything but ``MATCH_FOUND`` (so ``FILTER_MATCH_STATE_UNSPECIFIED`` passed), allowed a
missing or empty result whenever no per-filter finding was parsed, and never read
``invocationResult`` at all. ``PARTIAL`` and ``FAILURE`` arrive WITH ``NO_MATCH_FOUND``,
because a skipped filter reports no match: a prompt padded past the prompt-injection filter's
token limit went through unscreened.

**The remote A1 gateway** (``adapters/platform/remote_guardrail.py``) returns JSON, and its
``allowed`` holds only on a literal ``true``. ``bool(body["allowed"])`` read the string
``"false"`` as a pass.

Two levels, as in cio-advisory's test of the same rule:

* **SDK-free** (always runs, including the offline gate's SDK-free ``make check``): the
  responses are the REST wire shape, built from ``_MirrorState`` / ``_MirrorInvocation``,
  stdlib enums carrying the real member names and numbers.
* **Real SDK** (runs where ``google-cloud-modelarmor`` is installed, skips otherwise): the
  responses are real ``modelarmor_v1`` messages, rendered to the JSON the REST API returns
  with proto-plus's own ``to_json``, and screened through ``screen()`` with a fake HTTP
  client, so nothing touches the network. Its first test pins the mirror to the real enums.
"""

from __future__ import annotations

import enum
import json
from typing import Any

import httpx
import pytest
import respx

from trade_finance_checker.adapters.gcp import model_armor_guardrail as ma_module
from trade_finance_checker.adapters.gcp.model_armor_guardrail import ModelArmorGuardrailAdapter
from trade_finance_checker.adapters.platform.remote_guardrail import (
    RemoteGuardrailAdapter,
    RemoteGuardrailError,
)
from trade_finance_checker.config import Settings
from trade_finance_checker.domain.models import Direction

TEXT = "Please release the LC documents; the invoice amount is USD 250,000."
DIRECTIONS = [Direction.INPUT, Direction.OUTPUT]


class _MirrorState(enum.IntEnum):
    """``modelarmor_v1.FilterMatchState``'s members, by name and number."""

    FILTER_MATCH_STATE_UNSPECIFIED = 0
    NO_MATCH_FOUND = 1
    MATCH_FOUND = 2


class _MirrorInvocation(enum.IntEnum):
    """``modelarmor_v1.InvocationResult``'s members, by name and number."""

    INVOCATION_RESULT_UNSPECIFIED = 0
    SUCCESS = 1
    PARTIAL = 2
    FAILURE = 3


# --------------------------------------------------------------------------- #
# A fake HTTP client, so screen() runs end to end without the network or ADC
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, body: Any, status: int = 200) -> None:
        self._body = body
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code // 100 != 2:
            request = httpx.Request("POST", "https://modelarmor.example/v1")
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self) -> Any:
        return self._body


class _FakeClient:
    """Answers every POST with a canned body, or raises the canned error."""

    def __init__(
        self, body: Any = None, *, status: int = 200, error: Exception | None = None
    ) -> None:
        self._body = body
        self._status = status
        self._error = error
        self.urls: list[str] = []
        self.timeouts: list[Any] = []

    def post(self, url: str, *, json: Any, headers: Any, timeout: Any) -> _FakeResponse:
        self.urls.append(url)
        self.timeouts.append(timeout)
        if self._error is not None:
            raise self._error
        return _FakeResponse(self._body, self._status)


def _adapter(client: _FakeClient) -> ModelArmorGuardrailAdapter:
    adapter = ModelArmorGuardrailAdapter(Settings(project_id="p", profile="gcp"))
    adapter._client = client  # skip httpx.Client(); the mapping is what is under test
    adapter._bearer_token = lambda: "token"  # type: ignore[method-assign]  # skip ADC
    return adapter


def _screen(body: Any, direction: Direction = Direction.INPUT) -> Any:
    return _adapter(_FakeClient(body)).screen(TEXT, direction)


def _wire(
    state: _MirrorState | str | None,
    invocation: _MirrorInvocation | str | None = _MirrorInvocation.SUCCESS,
    filter_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A sanitize response in the REST wire shape: enums travel as their NAMES."""
    result: dict[str, Any] = {}
    if state is not None:
        result["filterMatchState"] = state.name if isinstance(state, enum.Enum) else state
    if invocation is not None:
        result["invocationResult"] = (
            invocation.name if isinstance(invocation, enum.Enum) else invocation
        )
    if filter_results is not None:
        result["filterResults"] = filter_results
    return {"sanitizationResult": result}


# --------------------------------------------------------------------------- #
# SDK-free: Model Armor
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("direction", DIRECTIONS)
def test_match_found_blocks_sdk_free(direction: Direction) -> None:
    verdict = _screen(_wire(_MirrorState.MATCH_FOUND), direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert verdict.findings, "a block must carry a finding"


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_no_match_found_with_success_allows_sdk_free(direction: Direction) -> None:
    verdict = _screen(_wire(_MirrorState.NO_MATCH_FOUND), direction)
    assert verdict.allowed is True
    assert verdict.sanitized_text == TEXT
    assert verdict.findings == ()


@pytest.mark.parametrize("direction", DIRECTIONS)
@pytest.mark.parametrize(
    "invocation",
    [
        _MirrorInvocation.PARTIAL,
        _MirrorInvocation.FAILURE,
        _MirrorInvocation.INVOCATION_RESULT_UNSPECIFIED,
        None,
    ],
    ids=["PARTIAL", "FAILURE", "UNSPECIFIED", "absent"],
)
def test_no_match_from_an_incomplete_screen_blocks_sdk_free(
    direction: Direction, invocation: _MirrorInvocation | None
) -> None:
    """A skipped filter reports no match. That is not a pass: the text was not screened."""
    verdict = _screen(_wire(_MirrorState.NO_MATCH_FOUND, invocation), direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert "no complete filter decision" in verdict.reason


@pytest.mark.parametrize("direction", DIRECTIONS)
@pytest.mark.parametrize("invocation", list(_MirrorInvocation), ids=lambda m: m.name)
def test_match_found_blocks_however_many_filters_ran_sdk_free(
    direction: Direction, invocation: _MirrorInvocation
) -> None:
    verdict = _screen(_wire(_MirrorState.MATCH_FOUND, invocation), direction)
    assert verdict.allowed is False


def test_exactly_one_combination_allows_sdk_free() -> None:
    allowed = [
        (state.name, invocation.name)
        for state in _MirrorState
        for invocation in _MirrorInvocation
        if _screen(_wire(state, invocation)).allowed
    ]
    assert allowed == [("NO_MATCH_FOUND", "SUCCESS")]


@pytest.mark.parametrize(
    "body",
    [
        _wire(_MirrorState.FILTER_MATCH_STATE_UNSPECIFIED),
        _wire(None, None),
        _wire(None),
        {"sanitizationResult": None},
        {},
        [],
        None,
        # Integer enums (``enum-encoding=int``) are not the wire this adapter asks for.
        _wire(int(_MirrorState.NO_MATCH_FOUND), int(_MirrorInvocation.SUCCESS)),  # type: ignore[arg-type]
        _wire("no_match_found", "success"),
    ],
    ids=[
        "unspecified-state",
        "empty-result",
        "state-absent",
        "null-result",
        "missing-result",
        "not-an-object",
        "null-body",
        "integer-enums",
        "lower-case",
    ],
)
def test_no_verdict_fails_closed_sdk_free(body: Any) -> None:
    verdict = _screen(body)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert verdict.findings, "a block must carry a finding"


def test_a_filter_hit_under_an_incomplete_screen_is_still_reported_sdk_free() -> None:
    body = _wire(
        _MirrorState.NO_MATCH_FOUND,
        _MirrorInvocation.PARTIAL,
        {"pi_and_jailbreak": {"piAndJailbreakFilterResult": {"matchState": "MATCH_FOUND"}}},
    )
    verdict = _screen(body)
    assert verdict.allowed is False
    assert [f.category.value for f in verdict.findings] == ["prompt_injection"]


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_every_call_carries_the_deadline(direction: Direction) -> None:
    client = _FakeClient(_wire(_MirrorState.NO_MATCH_FOUND))
    _adapter(client).screen(TEXT, direction)
    assert client.timeouts == [ma_module._TIMEOUT_SECONDS]
    assert 0 < client.timeouts[0] <= 60


@pytest.mark.parametrize(
    ("client", "raises"),
    [
        (_FakeClient(error=httpx.ReadTimeout("deadline exceeded")), httpx.ReadTimeout),
        (_FakeClient(error=httpx.ConnectError("unreachable")), httpx.ConnectError),
        (_FakeClient(_wire(_MirrorState.NO_MATCH_FOUND), status=503), httpx.HTTPStatusError),
    ],
    ids=["timeout", "connect-error", "http-503"],
)
def test_api_errors_propagate(client: _FakeClient, raises: type[Exception]) -> None:
    """An API failure must not turn into an allow; it reaches the caller."""
    with pytest.raises(raises):
        _adapter(client).screen(TEXT, Direction.INPUT)


# --------------------------------------------------------------------------- #
# SDK-free: the remote A1 gateway
# --------------------------------------------------------------------------- #
_GATEWAY = "http://localhost:8080/v1/guardrail/screen"


def _gateway_screen(body: Any) -> Any:
    with respx.mock:
        respx.post(_GATEWAY).respond(200, json=body)
        return RemoteGuardrailAdapter(Settings()).screen(TEXT, Direction.INPUT)


def test_gateway_literal_true_allows() -> None:
    assert _gateway_screen({"allowed": True, "direction": "input"}).allowed is True


@pytest.mark.parametrize(
    "allowed",
    [False, "false", "true", "False", 1, "1", "yes", {"v": True}, [True], None],
)
def test_gateway_anything_but_literal_true_blocks(allowed: Any) -> None:
    assert _gateway_screen({"allowed": allowed, "direction": "input"}).allowed is False


def test_gateway_missing_allowed_blocks() -> None:
    assert _gateway_screen({"direction": "input"}).allowed is False


@pytest.mark.parametrize("body", [[{"allowed": True}], True, "allowed", 0])
def test_gateway_non_object_body_raises(body: Any) -> None:
    with pytest.raises(RemoteGuardrailError):
        _gateway_screen(body)


def test_gateway_errors_raise() -> None:
    with respx.mock:
        respx.post(_GATEWAY).respond(503, json={"allowed": True})
        with pytest.raises(RemoteGuardrailError):
            RemoteGuardrailAdapter(Settings()).screen(TEXT, Direction.INPUT)


# --------------------------------------------------------------------------- #
# Real SDK: real modelarmor_v1 messages, in their REST JSON form, through screen()
# --------------------------------------------------------------------------- #
def _ma() -> Any:
    return pytest.importorskip("google.cloud.modelarmor_v1")


def _real_body(
    direction: Direction,
    state_name: str | None,
    invocation_name: str = "SUCCESS",
    *,
    skipped: bool = False,
) -> dict[str, Any]:
    """A real sanitize response as the REST API returns it; ``None`` leaves the result unset.

    ``skipped`` adds the prompt-injection filter as not having run, the shape a prompt padded
    past that filter's token limit produces.
    """
    ma = _ma()
    cls = (
        ma.SanitizeUserPromptResponse
        if direction is Direction.INPUT
        else ma.SanitizeModelResponseResponse
    )
    if state_name is None:
        message = cls()
    else:
        filter_results = {}
        if skipped:
            filter_results["pi_and_jailbreak"] = ma.FilterResult(
                pi_and_jailbreak_filter_result=ma.PiAndJailbreakFilterResult(
                    execution_state=ma.FilterExecutionState.EXECUTION_SKIPPED,
                    match_state=ma.FilterMatchState.NO_MATCH_FOUND,
                )
            )
        message = cls(
            sanitization_result=ma.SanitizationResult(
                filter_match_state=ma.FilterMatchState[state_name],
                invocation_result=ma.InvocationResult[invocation_name],
                filter_results=filter_results,
            )
        )
    # The REST API's JSON: camelCase field names, enums as their names.
    body: dict[str, Any] = json.loads(cls.to_json(message, use_integers_for_enums=False))
    return body


@pytest.mark.parametrize(
    ("mirror", "real_name"),
    [(_MirrorState, "FilterMatchState"), (_MirrorInvocation, "InvocationResult")],
    ids=["FilterMatchState", "InvocationResult"],
)
def test_the_mirror_matches_the_real_enum(mirror: Any, real_name: str) -> None:
    real = getattr(_ma(), real_name)
    assert {m.name: int(m) for m in real} == {m.name: int(m) for m in mirror}


def test_the_mirror_wire_shape_matches_the_real_one() -> None:
    body = _real_body(Direction.INPUT, "NO_MATCH_FOUND", "PARTIAL")
    assert body == _wire(_MirrorState.NO_MATCH_FOUND, _MirrorInvocation.PARTIAL, filter_results={})


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_match_found_blocks(direction: Direction) -> None:
    verdict = _screen(_real_body(direction, "MATCH_FOUND"), direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_no_match_found_with_success_allows(direction: Direction) -> None:
    verdict = _screen(_real_body(direction, "NO_MATCH_FOUND"), direction)
    assert verdict.allowed is True
    assert verdict.sanitized_text == TEXT


@pytest.mark.parametrize("direction", DIRECTIONS)
@pytest.mark.parametrize(
    "state_name",
    [None, "FILTER_MATCH_STATE_UNSPECIFIED"],
    ids=["missing-result", "unspecified-state"],
)
def test_no_verdict_fails_closed(direction: Direction, state_name: str | None) -> None:
    verdict = _screen(_real_body(direction, state_name), direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None


@pytest.mark.parametrize("direction", DIRECTIONS)
@pytest.mark.parametrize("invocation_name", ["PARTIAL", "FAILURE", "INVOCATION_RESULT_UNSPECIFIED"])
def test_no_match_from_a_screen_where_filters_did_not_run_blocks(
    direction: Direction, invocation_name: str
) -> None:
    body = _real_body(direction, "NO_MATCH_FOUND", invocation_name, skipped=True)
    verdict = _screen(body, direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert "no complete filter decision" in verdict.reason


def test_api_error_propagates_with_the_real_sdk_present() -> None:
    _ma()
    client = _FakeClient(_real_body(Direction.INPUT, "NO_MATCH_FOUND"), status=500)
    with pytest.raises(httpx.HTTPStatusError):
        _adapter(client).screen(TEXT, Direction.INPUT)
