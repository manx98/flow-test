package aibuilder

import "testing"

func TestBuildToolSpecs(t *testing.T) {
	specs := BuildToolSpecs()
	if len(specs) != len(ToolRisks) {
		t.Fatalf("tool count = %d risks = %d", len(specs), len(ToolRisks))
	}
	seen := map[string]ToolSpec{}
	for _, spec := range specs {
		if spec.Risk == "" {
			t.Fatalf("missing risk for %s", spec.Name)
		}
		seen[spec.Name] = spec
	}
	if seen["set_node_ports"].Risk != "write" {
		t.Fatalf("set_node_ports = %#v", seen["set_node_ports"])
	}
	if seen["validate_canvas"].Risk != "read" {
		t.Fatalf("validate_canvas = %#v", seen["validate_canvas"])
	}
}

func TestToolsForModelIncludesDynamicPortTypes(t *testing.T) {
	tools := ToolsForModel()
	tool := modelToolByName(tools, "set_node_ports")
	if tool == nil {
		t.Fatalf("set_node_ports missing from %#v", tools)
	}
	fn := tool["function"].(map[string]any)
	params := fn["parameters"].(map[string]any)
	props := params["properties"].(map[string]any)
	inputs := props["inputs"].(map[string]any)
	items := inputs["items"].(map[string]any)
	portProps := items["properties"].(map[string]any)
	typeSchema := portProps["type"].(map[string]any)
	enum := typeSchema["enum"].([]string)
	if !stringSliceContains(enum, "device") || !stringSliceContains(enum, "bool") || stringSliceContains(enum, "exec") {
		t.Fatalf("dynamic type enum = %#v", enum)
	}
}

func TestToolMetadataDoesNotExposeSchemas(t *testing.T) {
	meta := ToolMetadata()
	if len(meta) == 0 {
		t.Fatalf("metadata empty")
	}
	for _, item := range meta {
		if item["name"] == "" || item["risk"] == "" {
			t.Fatalf("metadata = %#v", item)
		}
		if _, ok := item["parameters"]; ok {
			t.Fatalf("metadata exposed schema = %#v", item)
		}
	}
}

func modelToolByName(tools []map[string]any, name string) map[string]any {
	for _, tool := range tools {
		fn, _ := tool["function"].(map[string]any)
		if fn["name"] == name {
			return tool
		}
	}
	return nil
}

func stringSliceContains(items []string, value string) bool {
	for _, item := range items {
		if item == value {
			return true
		}
	}
	return false
}
