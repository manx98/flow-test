# JSON输入

在节点内直接输入 JSON，并输出规范 JSON 文本。

## 使用建议

- 常用于生成 `api/request` 的 body 或 headers。
- 适合手写请求体、headers 或测试配置。
- 节点不再暴露 `value` 输入口；需要把脚本输出、变量输出等运行时对象转为 JSON 时，优先在脚本中生成文本或后续新增专用转换节点。
- 运行时读取 `value` 属性，并按 JSON 文本解析后再序列化。
- pretty=true 适合日志查看；发送请求时通常保持 false。
