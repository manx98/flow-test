# HTTP 请求

发送一次 HTTP 请求，并按状态码进入 success 或 fail 分支。

## 推荐模式

- GET 查询：填写 method=GET、url，读取 status/body/ok。
- POST/PUT/PATCH：填写 body；headers 用 JSON 对象，例如 `{"Authorization":"Bearer token"}`。
- 如果 body 是 JSON 且没有显式 Content-Type，节点会使用 content_type 属性作为默认 Content-Type。
- 需要严格失败中止流程时，开启 fail_on_error；否则非 2xx/3xx 会走 fail 分支但流程不会抛异常。
- 复杂响应判断：`body -> script/js_exec`，脚本里解析 JSON 后 `setResult('ok', bool)`，再接 `assert/check`。

## 注意事项

- headers 属性必须是 JSON 对象字符串。
- GET/HEAD 不发送 body。
- HTTP 4xx/5xx 会保留响应 body 并输出 status，不会丢失错误响应正文。
