package flow

import (
	"errors"
	"fmt"
	"strings"
	"time"
)

type AssertResult struct {
	OK       bool   `json:"ok"`
	Message  string `json:"message"`
	Node     int64  `json:"node"`
	Evidence string `json:"evidence,omitempty"`
}

type NodeErrorResult struct {
	Node     int64  `json:"node"`
	Message  string `json:"message"`
	Evidence string `json:"evidence,omitempty"`
}

type Report struct {
	Started  time.Time         `json:"-"`
	Finished time.Time         `json:"-"`
	Passed   bool              `json:"passed"`
	Error    string            `json:"error,omitempty"`
	Duration float64           `json:"duration"`
	Assert   []AssertResult    `json:"asserts"`
	Errors   []NodeErrorResult `json:"errors"`
	Total    int               `json:"total"`
	Failed   int               `json:"failed"`
	Logs     []string          `json:"logs"`
}

func NewReport() *Report {
	return &Report{Started: time.Now()}
}

func (r *Report) AddAssert(ok bool, message string, nodeID int64, evidence string) {
	r.Assert = append(r.Assert, AssertResult{OK: ok, Message: message, Node: nodeID, Evidence: evidence})
}

func (r *Report) AddError(nodeID int64, message string) {
	r.Errors = append(r.Errors, NodeErrorResult{Node: nodeID, Message: message})
}

func (r *Report) AddLog(message string) {
	r.Logs = append(r.Logs, message)
}

func (r *Report) Finalize(err error) {
	r.Finished = time.Now()
	r.Duration = float64(r.Finished.Sub(r.Started).Milliseconds()) / 1000
	if err != nil {
		r.Error = err.Error()
	}
	r.Total = len(r.Assert)
	r.Failed = 0
	for _, item := range r.Assert {
		if !item.OK {
			r.Failed++
		}
	}
	r.Passed = r.Error == "" && len(r.Errors) == 0 && r.Failed == 0
}

func ReportFromEvents(events []Event, err error) *Report {
	report := NewReport()
	for _, event := range events {
		switch event.Type {
		case "assert":
			report.AddAssert(event.Status == "ok", event.Info, event.ID, event.URL)
		case "alert":
			report.AddLog(event.Message)
		}
	}
	var nodeErr NodeError
	if errors.As(err, &nodeErr) {
		report.AddError(nodeErr.NodeID, nodeErr.Error())
	}
	report.Finalize(err)
	return report
}

func (r *Report) ToJUnit(suiteName string) string {
	if suiteName == "" {
		suiteName = "flow"
	}
	var out []string
	out = append(out, `<?xml version="1.0" encoding="UTF-8"?>`)
	out = append(out, fmt.Sprintf(
		`<testsuite name=%q tests="%d" failures="%d" errors="%d" time="%.3f">`,
		xmlAttr(suiteName), r.Total, r.Failed, len(r.Errors), r.Duration,
	))
	for _, item := range r.Assert {
		name := item.Message
		if name == "" {
			name = fmt.Sprintf("assert@node%d", item.Node)
		}
		out = append(out, fmt.Sprintf(`  <testcase classname="node%d" name=%q>`, item.Node, xmlAttr(name)))
		if !item.OK {
			detail := "assert failed"
			if item.Evidence != "" {
				detail += "\nevidence: " + item.Evidence
			}
			out = append(out, fmt.Sprintf(`    <failure message=%q>%s</failure>`, xmlAttr(name), xmlText(detail)))
		}
		out = append(out, "  </testcase>")
	}
	for _, item := range r.Errors {
		out = append(out, fmt.Sprintf(`  <testcase classname="node%d" name="error">`, item.Node))
		detail := item.Message
		if item.Evidence != "" {
			detail += "\nevidence: " + item.Evidence
		}
		out = append(out, fmt.Sprintf(`    <error message=%q>%s</error>`, xmlAttr(shortString(item.Message, 120)), xmlText(detail)))
		out = append(out, "  </testcase>")
	}
	if r.Error != "" && len(r.Errors) == 0 {
		out = append(out, `  <testcase classname="run" name="run">`)
		out = append(out, fmt.Sprintf(`    <error message=%q>%s</error>`, xmlAttr(r.Error), xmlText(r.Error)))
		out = append(out, "  </testcase>")
	}
	out = append(out, "</testsuite>")
	return strings.Join(out, "\n")
}

func xmlText(value string) string {
	return strings.NewReplacer(
		"&", "&amp;",
		"<", "&lt;",
		">", "&gt;",
	).Replace(value)
}

func xmlAttr(value string) string {
	return strings.NewReplacer(
		"&", "&amp;",
		"<", "&lt;",
		">", "&gt;",
		`"`, "&quot;",
		"'", "&apos;",
	).Replace(value)
}

func shortString(value string, max int) string {
	if max <= 0 || len(value) <= max {
		return value
	}
	return value[:max]
}
