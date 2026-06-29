# JS 脚本 (script/js)

定义 JavaScript 脚本，输出 `script` 句柄，连接到 `script/js_exec` 执行。

## 使用建议

- Go 重构版默认使用 JS 插件体系；当前 Python 运行器只展示该节点，不执行 JS。
- JS 适合封装循环、组合判断、重复 UI 操作和变量计算。
- 外部资源必须通过 `script/js_exec` 动态入参传入，例如设备、图片、OCR、文本、数字和布尔配置。
- 网络请求仍使用 `api/request`，不要在脚本里直接发起网络请求。
- 业务失败优先 `setResult('ok', false)`，再把 `ok` result 连接到断言和测试结果。
- JS 运行时由 Go 版 `goja` 提供，文件、网络、系统命令、动态 import、eval/Function 等能力默认禁止。
