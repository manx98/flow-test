package aibuilder

import "sort"

type ToolSpec struct {
	Name        string
	Risk        string
	Description string
	Parameters  map[string]any
	Required    []string
}

var ToolRisks = map[string]string{
	"inspect_canvas":    "read",
	"list_node_types":   "read",
	"read_node_spec":    "read",
	"create_node":       "write",
	"set_node_property": "write",
	"set_node_ports":    "write",
	"connect_nodes":     "write",
	"delete_node":       "write",
	"delete_link":       "write",
	"validate_canvas":   "read",
	"finish_build":      "read",
}

func BuildToolSpecs() []ToolSpec {
	refDesc := "Node reference. Use n1/n2 handles returned by create_node, or external:<canvas_node_id>."
	portSchema := map[string]any{
		"type": "array",
		"items": map[string]any{
			"type": "object",
			"properties": map[string]any{
				"name": map[string]any{"type": "string"},
				"type": map[string]any{"type": "string", "enum": sortedDynamicPortTypes()},
			},
			"required":             []string{"name", "type"},
			"additionalProperties": false,
		},
	}
	return []ToolSpec{
		toolSpec("inspect_canvas", "Read the current LiteGraph canvas summary and known handles.", map[string]any{
			"include_existing": map[string]any{"type": "boolean", "default": true},
			"include_created":  map[string]any{"type": "boolean", "default": true},
		}),
		toolSpec("list_node_types", "List available graph node types from the node catalog, optionally by category.", map[string]any{
			"category": map[string]any{"type": "string", "description": "Optional category, e.g. flow, action, vision."},
		}),
		toolSpec("read_node_spec", "Read one node type's inputs, outputs, properties, and usage summary.", map[string]any{
			"type": map[string]any{"type": "string", "description": "Node type, e.g. action/click."},
		}, "type"),
		toolSpec("create_node", "Create a real LiteGraph node on the user's canvas.", map[string]any{
			"type":       map[string]any{"type": "string"},
			"title":      map[string]any{"type": "string"},
			"pos":        map[string]any{"type": "array", "items": map[string]any{"type": "number"}, "minItems": 2, "maxItems": 2},
			"properties": map[string]any{"type": "object"},
		}, "type"),
		toolSpec("set_node_property", "Set a property on an existing canvas node.", map[string]any{
			"ref":   map[string]any{"type": "string", "description": refDesc},
			"name":  map[string]any{"type": "string"},
			"value": map[string]any{},
		}, "ref", "name", "value"),
		toolSpec("set_node_ports", "Set dynamic data inputs and result outputs on a script/js_exec node.", map[string]any{
			"ref":     map[string]any{"type": "string", "description": refDesc},
			"inputs":  portSchema,
			"outputs": portSchema,
		}, "ref"),
		toolSpec("connect_nodes", "Connect two nodes by named output/input ports.", map[string]any{
			"from":     map[string]any{"type": "string", "description": refDesc},
			"out":      map[string]any{"type": "string"},
			"to":       map[string]any{"type": "string", "description": refDesc},
			"in":       map[string]any{"type": "string"},
			"optional": map[string]any{"type": "boolean", "default": false},
		}, "from", "out", "to", "in"),
		toolSpec("delete_node", "Delete a node from the real canvas.", map[string]any{
			"ref": map[string]any{"type": "string", "description": refDesc},
		}, "ref"),
		toolSpec("delete_link", "Delete a link by endpoint references and port names.", map[string]any{
			"from": map[string]any{"type": "string", "description": refDesc},
			"out":  map[string]any{"type": "string"},
			"to":   map[string]any{"type": "string", "description": refDesc},
			"in":   map[string]any{"type": "string"},
		}, "from", "out", "to", "in"),
		toolSpec("validate_canvas", "Validate current canvas structure after edits.", map[string]any{}),
		toolSpec("finish_build", "Declare the build complete. The frontend will validate before final completion.", map[string]any{
			"summary": map[string]any{"type": "string"},
		}, "summary"),
	}
}

func ToolsForModel() []map[string]any {
	specs := BuildToolSpecs()
	out := make([]map[string]any, 0, len(specs))
	for _, spec := range specs {
		out = append(out, map[string]any{
			"type": "function",
			"function": map[string]any{
				"name":        spec.Name,
				"description": spec.Description,
				"parameters": map[string]any{
					"type":                 "object",
					"properties":           spec.Parameters,
					"required":             spec.Required,
					"additionalProperties": false,
				},
			},
		})
	}
	return out
}

func ToolMetadata() []map[string]any {
	specs := BuildToolSpecs()
	out := make([]map[string]any, 0, len(specs))
	for _, spec := range specs {
		out = append(out, map[string]any{
			"name":        spec.Name,
			"risk":        spec.Risk,
			"description": spec.Description,
		})
	}
	return out
}

func toolSpec(name, description string, parameters map[string]any, required ...string) ToolSpec {
	return ToolSpec{
		Name:        name,
		Risk:        ToolRisks[name],
		Description: description,
		Parameters:  parameters,
		Required:    required,
	}
}

func sortedDynamicPortTypes() []string {
	out := make([]string, 0, len(allowedDynamicPortTypes))
	for typ := range allowedDynamicPortTypes {
		out = append(out, typ)
	}
	sort.Strings(out)
	return out
}
