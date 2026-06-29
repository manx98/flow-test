"""Flow try/catch control node tests."""

from server.flow.engine import Engine


def _slot(name, typ, link=None, links=None):
    data = {"name": name, "type": typ}
    if link is not None:
        data["link"] = link
    if links is not None:
        data["links"] = links
    return data


def test_try_catch_handles_script_exception_and_continues():
    graph = {
        "nodes": [
            {
                "id": 1,
                "type": "flow/start",
                "outputs": [_slot("out", "exec", links=[1])],
            },
            {
                "id": 2,
                "type": "flow/try_catch",
                "inputs": [_slot("in", "exec", link=1)],
                "outputs": [
                    _slot("try", "exec", links=[2]),
                    _slot("catch", "exec", links=[4]),
                    _slot("done", "exec", links=[6]),
                    _slot("error", "text", links=[5]),
                    _slot("error_type", "text", links=[]),
                    _slot("error_node", "number", links=[]),
                ],
            },
            {
                "id": 3,
                "type": "script/python",
                "properties": {"code": "raise ValueError('boom')"},
                "outputs": [_slot("script", "script", links=[3])],
            },
            {
                "id": 4,
                "type": "script/exec",
                "inputs": [
                    _slot("in", "exec", link=2),
                    _slot("script", "script", link=3),
                ],
                "outputs": [_slot("out", "exec", links=[])],
            },
            {
                "id": 5,
                "type": "util/log",
                "properties": {"label": "handled"},
                "inputs": [
                    _slot("in", "exec", link=4),
                    _slot("value", "any", link=5),
                ],
                "outputs": [_slot("out", "exec", links=[])],
            },
            {
                "id": 6,
                "type": "util/log",
                "properties": {"label": "done"},
                "inputs": [_slot("in", "exec", link=6), _slot("value", "any")],
                "outputs": [_slot("out", "exec", links=[])],
            },
        ],
        "links": [
            [1, 1, 0, 2, 0, "exec"],
            [2, 2, 0, 4, 0, "exec"],
            [3, 3, 0, 4, 1, "script"],
            [4, 2, 1, 5, 0, "exec"],
            [5, 2, 3, 5, 1, "text"],
            [6, 2, 2, 6, 0, "exec"],
        ],
    }

    states = []
    report = Engine(graph).run(on_state=lambda *ev: states.append(ev))

    assert report.passed
    assert report.error is None
    assert report.errors == []
    assert report.logs == ["handled: boom", "done: None"]
    assert (4, "fail", "boom") in states
    assert any(ev == (2, "ok", "已捕获：boom") for ev in states)


def test_try_catch_handles_eval_exception_without_report_failure():
    graph = {
        "nodes": [
            {
                "id": 1,
                "type": "flow/start",
                "outputs": [_slot("out", "exec", links=[1])],
            },
            {
                "id": 2,
                "type": "flow/try_catch",
                "inputs": [_slot("in", "exec", link=1)],
                "outputs": [
                    _slot("try", "exec", links=[2]),
                    _slot("catch", "exec", links=[4]),
                    _slot("done", "exec", links=[6]),
                    _slot("error", "text", links=[5]),
                    _slot("error_type", "text", links=[]),
                    _slot("error_node", "number", links=[]),
                ],
            },
            {
                "id": 3,
                "type": "var/get",
                "properties": {"name": "missing"},
                "outputs": [_slot("value", "text", links=[3])],
            },
            {
                "id": 4,
                "type": "util/log",
                "properties": {"label": "try"},
                "inputs": [
                    _slot("in", "exec", link=2),
                    _slot("value", "any", link=3),
                ],
                "outputs": [_slot("out", "exec", links=[])],
            },
            {
                "id": 5,
                "type": "util/log",
                "properties": {"label": "handled"},
                "inputs": [
                    _slot("in", "exec", link=4),
                    _slot("value", "any", link=5),
                ],
                "outputs": [_slot("out", "exec", links=[])],
            },
            {
                "id": 6,
                "type": "util/log",
                "properties": {"label": "done"},
                "inputs": [_slot("in", "exec", link=6), _slot("value", "any")],
                "outputs": [_slot("out", "exec", links=[])],
            },
        ],
        "links": [
            [1, 1, 0, 2, 0, "exec"],
            [2, 2, 0, 4, 0, "exec"],
            [3, 3, 0, 4, 1, "text"],
            [4, 2, 1, 5, 0, "exec"],
            [5, 2, 3, 5, 1, "text"],
            [6, 2, 2, 6, 0, "exec"],
        ],
    }

    states = []
    report = Engine(graph).run(on_state=lambda *ev: states.append(ev))

    assert report.passed
    assert report.error is None
    assert report.errors == []
    assert "handled: 取变量失败：变量「missing」未设置" in report.logs[0]
    assert report.logs[1] == "done: None"
    assert any(ev[0] == 3 and ev[1] == "fail" for ev in states)


def test_raise_node_fails_report_when_uncaught():
    graph = {
        "nodes": [
            {
                "id": 1,
                "type": "flow/start",
                "outputs": [_slot("out", "exec", links=[1])],
            },
            {
                "id": 2,
                "type": "flow/raise",
                "properties": {"message": "manual fail"},
                "inputs": [_slot("in", "exec", link=1), _slot("message", "text")],
                "outputs": [],
            },
        ],
        "links": [[1, 1, 0, 2, 0, "exec"]],
    }

    states = []
    report = Engine(graph).run(on_state=lambda *ev: states.append(ev))

    assert not report.passed
    assert report.error == "manual fail"
    assert report.errors == [{"node": 2, "message": "manual fail", "evidence": None}]
    assert (2, "fail", "manual fail") in states


def test_try_catch_handles_raise_node():
    graph = {
        "nodes": [
            {
                "id": 1,
                "type": "flow/start",
                "outputs": [_slot("out", "exec", links=[1])],
            },
            {
                "id": 2,
                "type": "flow/try_catch",
                "inputs": [_slot("in", "exec", link=1)],
                "outputs": [
                    _slot("try", "exec", links=[2]),
                    _slot("catch", "exec", links=[3]),
                    _slot("done", "exec", links=[5]),
                    _slot("error", "text", links=[4]),
                    _slot("error_type", "text", links=[]),
                    _slot("error_node", "number", links=[]),
                ],
            },
            {
                "id": 3,
                "type": "flow/raise",
                "properties": {"message": "manual caught"},
                "inputs": [_slot("in", "exec", link=2), _slot("message", "text")],
                "outputs": [],
            },
            {
                "id": 4,
                "type": "util/log",
                "properties": {"label": "handled"},
                "inputs": [
                    _slot("in", "exec", link=3),
                    _slot("value", "any", link=4),
                ],
                "outputs": [_slot("out", "exec", links=[])],
            },
            {
                "id": 5,
                "type": "util/log",
                "properties": {"label": "done"},
                "inputs": [_slot("in", "exec", link=5), _slot("value", "any")],
                "outputs": [_slot("out", "exec", links=[])],
            },
        ],
        "links": [
            [1, 1, 0, 2, 0, "exec"],
            [2, 2, 0, 3, 0, "exec"],
            [3, 2, 1, 4, 0, "exec"],
            [4, 2, 3, 4, 1, "text"],
            [5, 2, 2, 5, 0, "exec"],
        ],
    }

    states = []
    report = Engine(graph).run(on_state=lambda *ev: states.append(ev))

    assert report.passed
    assert report.error is None
    assert report.errors == []
    assert report.logs == ["handled: manual caught", "done: None"]
    assert (3, "fail", "manual caught") in states
    assert any(ev == (2, "ok", "已捕获：manual caught") for ev in states)
