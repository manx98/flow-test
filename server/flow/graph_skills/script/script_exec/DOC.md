# Python 执行 (script/exec)

## 用法

- 动态添加入参/result 端口，脚本中用 get_arg 和 set_result 读写。
- AI 搭建复杂流程时，先创建 `script/python`，再创建本节点，随后添加资源入参和业务结果输出。
- 入参类型限定为常用数据端口：match/point/text/number/bool/picture/mask/ocr/device/script。
- 推荐把设备、模板图片、mask、OCR 和配置值都接到入参端口；脚本不要硬编码这些资源。
- 推荐添加 `ok:bool` result 端口，并连接到 `assert/check`，最后进入 `test/result`。
