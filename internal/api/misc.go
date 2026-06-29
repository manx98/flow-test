package api

import (
	"net/http"
	"regexp"
	"sort"
	"strings"

	"flow-test-go/internal/project"

	"github.com/dop251/goja/parser"
	"github.com/gin-gonic/gin"
)

func (s *Server) getSettings(c *gin.Context) {
	settings, err := project.LoadSettings()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"settings": settings})
}

func (s *Server) putSettings(c *gin.Context) {
	var body struct {
		Settings map[string]any `json:"settings"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	if err := project.SaveSettings(body.Settings); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (s *Server) checkCode(c *gin.Context) {
	var body struct {
		Code string `json:"code"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	if _, err := parser.ParseFile(nil, "script.js", body.Code, 0); err != nil {
		c.JSON(http.StatusOK, gin.H{"errors": parserErrors(err)})
		return
	}
	c.JSON(http.StatusOK, gin.H{"errors": []any{}})
}

func (s *Server) completeCode(c *gin.Context) {
	var body struct {
		Code   string `json:"code"`
		Line   int    `json:"line"`
		Column int    `json:"column"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	prefix, pool := completionContext(body.Code, body.Line, body.Column)
	c.JSON(http.StatusOK, gin.H{"completions": completionItems(prefix, pool)})
}

func parserErrors(err error) []gin.H {
	if list, ok := err.(parser.ErrorList); ok {
		out := make([]gin.H, 0, len(list))
		for _, item := range list {
			out = append(out, parserError(item))
		}
		return out
	}
	if item, ok := err.(*parser.Error); ok {
		return []gin.H{parserError(item)}
	}
	return []gin.H{{"line": 1, "col": 1, "end_line": 1, "end_col": 2, "message": err.Error()}}
}

func parserError(item *parser.Error) gin.H {
	line := item.Position.Line
	col := item.Position.Column
	if line < 1 {
		line = 1
	}
	if col < 1 {
		col = 1
	}
	return gin.H{
		"line":     line,
		"col":      col,
		"end_line": line,
		"end_col":  col + 1,
		"message":  item.Message,
	}
}

var wordPattern = regexp.MustCompile(`[A-Za-z_$][A-Za-z0-9_$]{1,}`)

var jsGlobals = []string{
	"getArg", "setResult", "log", "pc", "flow", "vars", "device", "JSON", "Math", "Array", "Object", "String",
	"Number", "Boolean", "Date", "RegExp", "Error", "true", "false", "null", "undefined", "const", "let", "var",
	"function", "return", "if", "else", "for", "while", "do", "switch", "case", "break", "continue", "try", "catch",
	"finally", "throw", "class", "new", "async", "await",
}

var jsMembers = map[string][]string{
	"pc":     {"click", "type", "hotkey", "findImage", "findAll", "findText", "wait", "log"},
	"device": {"click", "type", "hotkey", "capture"},
	"flow":   {"image", "find_image", "find_all", "find_text", "wait_appear", "wait_vanish", "to_point", "click", "type_text", "scroll", "drag", "delay", "log", "alert", "get_var", "set_var"},
	"vars":   {"get", "set", "keys"},
	"JSON":   {"parse", "stringify"},
	"Math":   {"abs", "ceil", "floor", "max", "min", "round", "random"},
	"Array":  {"isArray", "from"},
	"Object": {"keys", "values", "entries", "assign"},
	"String": {"fromCharCode"},
	"Number": {"isFinite", "isInteger", "parseFloat", "parseInt"},
}

func completionContext(code string, line, column int) (string, []string) {
	pos := offsetForLineColumn(code, line, column)
	left := code[:pos]
	word := currentIdentifier(left)
	before := strings.TrimSpace(strings.TrimSuffix(left, word))
	if strings.HasSuffix(before, ".") {
		owner := currentIdentifier(strings.TrimSuffix(before, "."))
		return word, jsMembers[owner]
	}
	pool := append([]string{}, jsGlobals...)
	pool = append(pool, wordPattern.FindAllString(code, -1)...)
	return word, pool
}

func offsetForLineColumn(code string, line, column int) int {
	if line <= 1 {
		if column < 0 {
			return 0
		}
		if column > len(code) {
			return len(code)
		}
		return column
	}
	currentLine := 1
	for i, r := range code {
		if currentLine == line {
			end := i + column
			if end < i {
				return i
			}
			if end > len(code) {
				return len(code)
			}
			return end
		}
		if r == '\n' {
			currentLine++
		}
	}
	return len(code)
}

func currentIdentifier(text string) string {
	end := len(text)
	start := end
	for start > 0 {
		ch := text[start-1]
		if (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') || ch == '_' || ch == '$' {
			start--
			continue
		}
		break
	}
	if start == end {
		return ""
	}
	return text[start:end]
}

func completionItems(prefix string, pool []string) []gin.H {
	seen := map[string]bool{}
	names := make([]string, 0, len(pool))
	for _, name := range pool {
		if name == "" || seen[name] || !strings.HasPrefix(name, prefix) {
			continue
		}
		seen[name] = true
		names = append(names, name)
	}
	sort.Strings(names)
	if len(names) > 20 {
		names = names[:20]
	}
	out := make([]gin.H, 0, len(names))
	for _, name := range names {
		out = append(out, gin.H{"name": name, "type": completionType(name)})
	}
	return out
}

func completionType(name string) string {
	switch name {
	case "true", "false", "null", "undefined":
		return "constant"
	case "const", "let", "var", "function", "return", "if", "else", "for", "while", "try", "catch", "throw", "class", "new":
		return "keyword"
	default:
		return "function"
	}
}
