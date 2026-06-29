# JS 执行 (script/js_exec)

执行 `script/js` 输出的脚本句柄，并通过动态端口传入资源、输出结果。

## 使用建议

- 复杂逻辑流程中先创建 `script/js`，再创建本节点。
- 动态入参用于传入设备、图片、mask、OCR、文本、数字和布尔配置。
- 动态 result 用于输出 `ok`、`message`、`point` 等业务结果。
- 运行成功不代表业务成功；业务成功/失败应由脚本设置 result，例如 `setResult('ok', found.ok)`。
- Go 版 runner 必须提供超时、goja interrupt 和 abort 检查，避免死循环卡住运行器。
