import asyncio

import httpx
import pytest

from connhex import AsyncConnhex, Connhex
from connhex.errors import (
    AuthenticationError,
    InvalidResponseError,
    NotFoundError,
    PermissionDeniedError,
)


@pytest.fixture(params=["async", "sync"])
def call(request):
    def invoke(handler, method, *args, **kwargs):
        if request.param == "async":

            async def run():
                async with AsyncConnhex(token="test", max_retries=0) as c:
                    await c._http._http.aclose()
                    c._http._http = httpx.AsyncClient(
                        transport=httpx.MockTransport(handler)
                    )
                    return await getattr(c.iam, method)(*args, **kwargs)

            return asyncio.run(run())
        with Connhex(token="test", max_retries=0) as c:
            c._http._http.close()
            c._http._http = httpx.Client(transport=httpx.MockTransport(handler))
            return getattr(c.iam, method)(*args, **kwargs)

    return invoke


def test_get_identity_omits_credentials(call):
    def handler(request):
        assert request.url.path == "/iam/identities/test-id"
        assert request.url.host == "apis.connhex.com"
        assert "include_credential" not in request.url.params
        return httpx.Response(
            200,
            json={
                "id": "test-id",
                "traits": {"custom": "value"},
                "credentials": {"password": {"secret": "excluded"}},
                "metadata_admin": {"custom": True},
                "future_field": 42,
            },
        )

    identity = call(handler, "get_identity", "test-id")
    assert identity.traits == {"custom": "value"}
    assert identity.metadata_admin == {"custom": True}
    assert identity.model_dump()["future_field"] == 42
    assert "credentials" not in identity.model_dump()
    assert "excluded" not in identity.model_dump_json()


@pytest.mark.parametrize(
    "count,offset,limit",
    [
        (0, 0, 3),
        (9, 0, 3),
        (9, 3, 3),
        (9, 1, 5),
        (9, 7, 3),
        (9, 9, 3),
        (9, 20, 3),
        (110, 101, 4),
    ],
)
def test_offset_pagination(call, count, offset, limit):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/iam/identities"
        assert request.url.params["credentials_identifier"] == "a@test.com"
        start = int(request.url.params.get("page_token", "0"))
        size = min(2, int(request.url.params["page_size"]))
        stop = min(count, start + size)
        headers = {}
        if stop < count:
            headers["link"] = (
                f'</admin/identities?page_token={stop}>; rel="next"'
            )
        return httpx.Response(
            200,
            json=[
                {"id": str(i), "credentials": {}} for i in range(start, stop)
            ],
            headers=headers,
        )

    page = call(
        handler,
        "list_identities",
        limit=limit,
        offset=offset,
        credentials_identifier="a@test.com",
    )
    assert [i.id for i in page.identities] == [
        str(i) for i in range(count)[offset : offset + limit]
    ]
    assert page.has_more == (count > offset + limit)
    assert page.next_offset == (offset + limit if page.has_more else None)
    assert page.limit == limit and page.offset == offset
    assert "page_token" not in page.model_dump_json()
    assert "credentials" not in page.model_dump_json()
    assert all(int(r.url.params["page_size"]) <= 100 for r in requests)


@pytest.mark.parametrize("limit,offset", [(0, 0), (-1, 0), (1, -1)])
def test_invalid_pagination_input(call, limit, offset):
    def handler(request):
        pytest.fail("Invalid arguments must not issue requests")

    with pytest.raises(ValueError):
        call(handler, "list_identities", limit=limit, offset=offset)


@pytest.mark.parametrize(
    "payload,link",
    [
        ({}, None),
        ([{}], None),
        (None, None),
        ([{"id": "one"}], '</admin/identities>; rel="next"'),
        ([], '</admin/identities?page_token=x>; rel="next"'),
    ],
)
def test_invalid_list_response(call, payload, link):
    def handler(request):
        return httpx.Response(
            200, json=payload, headers={"link": link} if link else {}
        )

    with pytest.raises(InvalidResponseError):
        call(handler, "list_identities")


def test_repeated_cursor(call):
    def handler(request):
        return httpx.Response(
            200,
            json=[{"id": "one"}],
            headers={"link": '</admin/identities?page_token=x>; rel="next"'},
        )

    with pytest.raises(InvalidResponseError, match="Repeated"):
        call(handler, "list_identities")


@pytest.mark.parametrize(
    "status,error",
    [
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
    ],
)
@pytest.mark.parametrize("method", ["get_identity", "list_identities"])
def test_api_errors(call, status, error, method):
    def handler(request):
        return httpx.Response(status, json={"error": {"message": "denied"}})

    with pytest.raises(error):
        call(handler, method, *(["id"] if method == "get_identity" else []))


def test_later_page_error_is_not_partial_success(call):
    def handler(request):
        if "page_token" in request.url.params:
            return httpx.Response(403, json={"error": {"message": "denied"}})
        return httpx.Response(
            200,
            json=[{"id": "one"}],
            headers={"link": '</admin/identities?page_token=x>; rel="next"'},
        )

    with pytest.raises(PermissionDeniedError):
        call(handler, "list_identities")


@pytest.mark.parametrize("method", ["get_identity", "list_identities"])
def test_invalid_json(call, method):
    def handler(request):
        return httpx.Response(200, text="not json")

    with pytest.raises(InvalidResponseError):
        call(handler, method, *(["id"] if method == "get_identity" else []))
