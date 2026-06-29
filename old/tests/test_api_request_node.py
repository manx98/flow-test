"""HTTP API request graph node tests."""

from __future__ import annotations

import io
import urllib.error
from email.message import Message

from server.flow.engine import Engine


def _slot(name, typ, link=None, links=None):
    data = {"name": name, "type": typ}
    if link is not None:
        data["link"] = link
    if links is not None:
        data["links"] = links
    return data


class _Response:
    def __init__(self, status: int, body: str, content_type: str = "text/plain; charset=utf-8"):
        self.status = status
        self._body = body.encode("utf-8")
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return self._body


def _request_graph(props, success_links=None, fail_links=None, body_links=None):
    return {
        "nodes": [
            {"id": 1, "type": "flow/start", "outputs": [_slot("out", "exec", links=[1])]},
            {
                "id": 2,
                "type": "api/request",
                "properties": props,
                "inputs": [_slot("in", "exec", link=1), _slot("url", "text"), _slot("headers", "text"), _slot("body", "text")],
                "outputs": [
                    _slot("success", "exec", links=success_links or []),
                    _slot("fail", "exec", links=fail_links or []),
                    _slot("status", "number", links=[]),
                    _slot("body", "text", links=body_links or []),
                    _slot("ok", "bool", links=[]),
                ],
            },
            {
                "id": 3,
                "type": "util/log",
                "properties": {"label": "body"},
                "inputs": [_slot("in", "exec"), _slot("value", "any")],
                "outputs": [_slot("out", "exec", links=[])],
            },
        ],
        "links": [[1, 1, 0, 2, 0, "exec"]],
    }


def _connect_log(graph, from_exec_slot: int):
    graph["nodes"][2]["inputs"][0]["link"] = 2
    graph["nodes"][2]["inputs"][1]["link"] = 3
    graph["links"].extend([
        [2, 2, from_exec_slot, 3, 0, "exec"],
        [3, 2, 3, 3, 1, "text"],
    ])
    return graph


def test_api_request_get_success_outputs_status_body_and_ok(monkeypatch):
    def fake_urlopen(req, timeout):
        assert req.full_url == "http://example.test/ok"
        assert req.get_method() == "GET"
        assert timeout == 15
        return _Response(200, '{"ok":true}', "application/json; charset=utf-8")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    graph = _connect_log(
        _request_graph({"method": "GET", "url": "http://example.test/ok"}, success_links=[2], body_links=[3]),
        0,
    )
    report = Engine(graph).run()

    assert report.passed
    assert report.logs == ['body: {"ok":true}']


def test_api_request_post_uses_body_and_default_content_type(monkeypatch):
    def fake_urlopen(req, timeout):
        assert req.get_method() == "POST"
        assert req.data == b'{"x":1}'
        assert req.headers["Content-type"].startswith("application/json")
        return _Response(201, "created")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    graph = _connect_log(
        _request_graph({"method": "POST", "url": "http://example.test/post", "body": "{\"x\":1}"}, success_links=[2], body_links=[3]),
        0,
    )
    report = Engine(graph).run()

    assert report.passed
    assert report.logs == ["body: created"]


def test_api_request_non_2xx_goes_to_fail_branch_without_raising(monkeypatch):
    def fake_urlopen(req, timeout):
        headers = Message()
        headers["Content-Type"] = "text/plain; charset=utf-8"
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", headers, io.BytesIO(b"missing"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    graph = _connect_log(
        _request_graph({"method": "GET", "url": "http://example.test/missing"}, fail_links=[2], body_links=[3]),
        1,
    )
    report = Engine(graph).run()

    assert report.passed
    assert report.logs == ["body: missing"]


def test_api_request_fail_on_error_raises(monkeypatch):
    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    graph = _request_graph({"method": "GET", "url": "http://example.test/down", "fail_on_error": True})
    report = Engine(graph).run()

    assert not report.passed
    assert "HTTP 请求失败" in report.error
