from server.flow.engine import Engine


def _slot(name, typ, link=None, links=None):
    data = {"name": name, "type": typ}
    if link is not None:
        data["link"] = link
    if links is not None:
        data["links"] = links
    return data


def test_text_display_emits_and_passes_text():
    graph = {
        "nodes": [
            {"id": 1, "type": "flow/start", "outputs": [_slot("out", "exec", links=[1])]},
            {
                "id": 2,
                "type": "const/text",
                "properties": {"value": "hello\nworld"},
                "outputs": [_slot("text", "text", links=[2])],
            },
            {
                "id": 3,
                "type": "data/text_display",
                "properties": {"placeholder": ""},
                "inputs": [_slot("in", "exec", link=1), _slot("text", "text", link=2)],
                "outputs": [_slot("out", "exec", links=[3]), _slot("text", "text", links=[4])],
            },
            {
                "id": 4,
                "type": "util/log",
                "properties": {"label": "shown"},
                "inputs": [_slot("in", "exec", link=3), _slot("value", "any", link=4)],
                "outputs": [_slot("out", "exec", links=[])],
            },
        ],
        "links": [
            [1, 1, 0, 3, 0, "exec"],
            [2, 2, 0, 3, 1, "text"],
            [3, 3, 0, 4, 0, "exec"],
            [4, 3, 1, 4, 1, "text"],
        ],
    }
    events = []

    report = Engine(graph).run(on_event=events.append)

    assert report.passed
    assert report.logs == ["shown: hello\nworld"]
    assert {"type": "node_text", "id": 3, "text": "hello\nworld"} in events
