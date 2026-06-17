import pytest

from server.flow.ai_builder import AIBuilderError, compile_graph_patch


def _script_patch(script_code: str = "set_result('ok', True)") -> dict:
    return {
        "title": "script flow",
        "summary": "uses script for complex logic",
        "entry": "run",
        "nodes": [
            {
                "id": "dev",
                "type": "device/local",
                "pos": [120, 80],
                "properties": {"monitor": 1},
            },
            {
                "id": "py",
                "type": "script/python",
                "pos": [120, 220],
                "properties": {"code": script_code},
            },
            {
                "id": "run",
                "type": "script/exec",
                "pos": [420, 220],
                "inputs": [{"name": "dev", "type": "device"}],
                "outputs": [{"name": "ok", "type": "bool"}],
                "properties": {},
            },
            {
                "id": "check",
                "type": "assert/check",
                "pos": [720, 220],
                "properties": {"message": "script succeeded"},
            },
            {
                "id": "result",
                "type": "test/result",
                "pos": [1020, 220],
                "properties": {},
            },
        ],
        "links": [
            {"from": "py", "out": "script", "to": "run", "in": "script"},
            {"from": "dev", "out": "device", "to": "run", "in": "dev"},
            {"from": "run", "out": "out", "to": "check", "in": "in"},
            {"from": "run", "out": "ok", "to": "check", "in": "cond"},
            {"from": "check", "out": "pass", "to": "result", "in": "in"},
        ],
    }


def test_compile_graph_patch_accepts_script_exec_dynamic_ports():
    draft = compile_graph_patch(_script_patch())

    exec_node = next(n for n in draft["nodes"] if n["id"] == "run")
    assert exec_node["inputs"] == [{"name": "dev", "type": "device"}]
    assert exec_node["outputs"] == [{"name": "ok", "type": "bool"}]
    assert any(link["out"] == "ok" and link["in"] == "cond" for link in draft["links"])


def test_compile_graph_patch_rejects_dynamic_ports_on_non_script_exec():
    patch = _script_patch()
    patch["nodes"][1]["outputs"] = [{"name": "ok", "type": "bool"}]

    with pytest.raises(AIBuilderError, match="cannot declare dynamic ports"):
        compile_graph_patch(patch)


@pytest.mark.parametrize(
    "ports, message",
    [
        ([{"name": "ok", "type": "any"}], "invalid dynamic port"),
        ([{"name": "ok", "type": "bool"}, {"name": "ok", "type": "bool"}], "duplicate dynamic port"),
        ([{"name": "out", "type": "bool"}], "cannot override fixed port"),
    ],
)
def test_compile_graph_patch_rejects_bad_script_exec_dynamic_outputs(ports, message):
    patch = _script_patch()
    patch["nodes"][2]["outputs"] = ports

    with pytest.raises(AIBuilderError, match=message):
        compile_graph_patch(patch)


def test_compile_graph_patch_rejects_bad_script_python_syntax():
    with pytest.raises(AIBuilderError, match="script/python code line"):
        compile_graph_patch(_script_patch("if True\n    pass"))

