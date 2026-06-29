package flow

import (
	"strings"
	"testing"
)

func TestReportFromEvents(t *testing.T) {
	report := ReportFromEvents([]Event{
		{Type: "assert", ID: 1, Status: "ok", Info: "first"},
		{Type: "assert", ID: 2, Status: "fail", Info: "second", URL: "shot.png"},
		{Type: "alert", ID: 3, Message: "hello"},
	}, nil)
	if report.Passed {
		t.Fatalf("Passed = true, want false")
	}
	if report.Total != 2 || report.Failed != 1 {
		t.Fatalf("total/failed = %d/%d, want 2/1", report.Total, report.Failed)
	}
	if len(report.Logs) != 1 || report.Logs[0] != "hello" {
		t.Fatalf("logs = %#v", report.Logs)
	}
	if report.Assert[1].Evidence != "shot.png" {
		t.Fatalf("evidence = %#v", report.Assert[1].Evidence)
	}
}

func TestReportIgnoresNodeFailEventsWithoutRunError(t *testing.T) {
	report := ReportFromEvents([]Event{
		{Type: "node", ID: 3, Status: "fail", Info: "caught"},
		{Type: "run", Status: "done"},
	}, nil)
	if !report.Passed {
		t.Fatalf("Passed = false, want true: %#v", report)
	}
	if len(report.Errors) != 0 {
		t.Fatalf("errors = %#v, want none", report.Errors)
	}
}

func TestReportAddsUncaughtNodeError(t *testing.T) {
	err := NodeError{NodeID: 7, Type: "flow/raise", Err: errString("boom")}
	report := ReportFromEvents(nil, err)
	if report.Passed {
		t.Fatalf("Passed = true, want false")
	}
	if len(report.Errors) != 1 || report.Errors[0].Node != 7 || report.Errors[0].Message != "boom" {
		t.Fatalf("errors = %#v", report.Errors)
	}
}

func TestReportToJUnit(t *testing.T) {
	report := ReportFromEvents([]Event{
		{Type: "assert", ID: 1, Status: "ok", Info: "ok <case>"},
		{Type: "assert", ID: 2, Status: "fail", Info: `bad "case"`},
	}, NodeError{NodeID: 3, Type: "flow/raise", Err: errString("boom & break")})
	xml := report.ToJUnit("flow:demo")
	for _, want := range []string{
		`<testsuite`,
		`tests="2"`,
		`failures="1"`,
		`errors="1"`,
		`bad &quot;case&quot;`,
		`boom &amp; break`,
	} {
		if !strings.Contains(xml, want) {
			t.Fatalf("JUnit missing %q:\n%s", want, xml)
		}
	}
}

type errString string

func (e errString) Error() string {
	return string(e)
}
