"""API JSON/form serialization node tests."""

from server.flow.engine import Engine


def _slot(name, typ, link=None, links=None):
    data = {"name": name, "type": typ}
    if link is not None:
        data["link"] = link
    if links is not None:
        data["links"] = links
    return data


def _log_graph(value_node, value_output_slot=0, value_link_type="text"):
    value_node.setdefault("outputs", [])
    return {
        "nodes": [
            {"id": 1, "type": "flow/start", "outputs": [_slot("out", "exec", links=[1])]},
            value_node,
            {
                "id": 3,
                "type": "util/log",
                "properties": {"label": "value"},
                "inputs": [_slot("in", "exec", link=1), _slot("value", "any", link=2)],
                "outputs": [_slot("out", "exec", links=[])],
            },
        ],
        "links": [
            [1, 1, 0, 3, 0, "exec"],
            [2, value_node["id"], value_output_slot, 3, 1, value_link_type],
        ],
    }


def test_json_serialize_from_property():
    graph = _log_graph({
        "id": 2,
        "type": "api/json_serialize",
        "properties": {"value": "{\"name\":\"flow\",\"n\":2}"},
        "inputs": [],
        "outputs": [_slot("text", "text", links=[2])],
    })

    report = Engine(graph).run()

    assert report.passed
    assert report.logs == ['value: {"name": "flow", "n": 2}']


def test_form_serialize_from_json_property():
    graph = _log_graph({
        "id": 2,
        "type": "api/form_serialize",
        "properties": {"value": "{\"a\":\"hello world\",\"tag\":[\"x\",\"y\"]}"},
        "inputs": [_slot("value", "any")],
        "outputs": [_slot("text", "text", links=[2])],
    })

    report = Engine(graph).run()

    assert report.passed
    assert report.logs == ["value: a=hello+world&tag=x&tag=y"]
