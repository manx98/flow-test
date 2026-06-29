package jsplugin

import (
	"context"
	"fmt"
	"time"

	"github.com/dop251/goja"
)

type Runtime struct {
	Timeout time.Duration
}

type Request struct {
	Code string
	Args map[string]any
}

type Response struct {
	Results map[string]any
	Logs    []string
}

func NewRuntime() *Runtime {
	return &Runtime{Timeout: 30 * time.Second}
}

func (r *Runtime) Run(ctx context.Context, req Request) (Response, error) {
	if r.Timeout <= 0 {
		r.Timeout = 30 * time.Second
	}
	ctx, cancel := context.WithTimeout(ctx, r.Timeout)
	defer cancel()
	vm := goja.New()
	results := map[string]any{}
	logs := []string{}
	if req.Args == nil {
		req.Args = map[string]any{}
	}
	bind := bindings{ctx: ctx, vm: vm, logs: &logs}

	mustSet := func(name string, value any) {
		if err := vm.Set(name, value); err != nil {
			panic(err)
		}
	}
	mustSet("getArg", func(call goja.FunctionCall) goja.Value {
		name := call.Argument(0).String()
		value, ok := req.Args[name]
		if !ok {
			return call.Argument(1)
		}
		return bind.wrapArg(value)
	})
	mustSet("setResult", func(call goja.FunctionCall) goja.Value {
		name := call.Argument(0).String()
		if name == "" {
			panic(vm.ToValue("setResult requires a non-empty name"))
		}
		results[name] = call.Argument(1).Export()
		return goja.Undefined()
	})
	mustSet("log", func(call goja.FunctionCall) goja.Value {
		logs = append(logs, call.Argument(0).String())
		return goja.Undefined()
	})
	disabled := func(goja.FunctionCall) goja.Value {
		panic(vm.ToValue("disabled in flow JS runtime"))
	}
	mustSet("eval", disabled)
	mustSet("Function", disabled)

	done := make(chan struct{})
	go func() {
		select {
		case <-ctx.Done():
			vm.Interrupt(ctx.Err())
		case <-done:
		}
	}()
	defer close(done)

	if _, err := vm.RunString(req.Code); err != nil {
		if ctxErr := ctx.Err(); ctxErr != nil {
			return Response{}, ctxErr
		}
		return Response{}, fmt.Errorf("JS runtime error: %w", err)
	}
	return Response{Results: results, Logs: logs}, nil
}
