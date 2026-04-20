from __future__ import annotations

import asyncio
import logging
from unittest.mock import Mock

from aiohttp import ClientConnectorError, ClientResponseError, RequestInfo
import pytest
from yarl import URL

from custom_components.swissweather.request import async_get_with_retry


class _Response:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    async def json(self):
        return self._payload


def _connector_error() -> ClientConnectorError:
    return ClientConnectorError(Mock(), OSError("dns failed"))


def _response_error(status: int) -> ClientResponseError:
    return ClientResponseError(
        RequestInfo(URL("https://example.com"), "GET", {}, URL("https://example.com")),
        (),
        status=status,
        message=f"HTTP {status}",
    )


def test_async_get_with_retry_retries_transient_connector_errors(monkeypatch):
    calls = 0
    original_sleep = asyncio.sleep

    class _Session:
        def get(self, url, **kwargs):
            nonlocal calls
            del url, kwargs
            calls += 1
            if calls < 3:
                raise _connector_error()
            return _Response({"ok": True})

    async def _parse_json(response):
        return await response.json()

    async def _run():
        return await async_get_with_retry(
            _Session(),
            "https://example.com",
            logger=logging.getLogger(__name__),
            response_handler=_parse_json,
        )

    monkeypatch.setattr(asyncio, "sleep", lambda *_args, **_kwargs: original_sleep(0))
    assert asyncio.run(_run()) == {"ok": True}
    assert calls == 3


def test_async_get_with_retry_does_not_retry_non_transient_http_errors(monkeypatch):
    calls = 0
    original_sleep = asyncio.sleep

    class _Session:
        def get(self, url, **kwargs):
            nonlocal calls
            del url, kwargs
            calls += 1
            raise _response_error(404)

    async def _parse_json(response):
        return await response.json()

    async def _run():
        await async_get_with_retry(
            _Session(),
            "https://example.com",
            logger=logging.getLogger(__name__),
            response_handler=_parse_json,
        )

    monkeypatch.setattr(asyncio, "sleep", lambda *_args, **_kwargs: original_sleep(0))
    with pytest.raises(ClientResponseError, match="HTTP 404"):
        asyncio.run(_run())
    assert calls == 1
