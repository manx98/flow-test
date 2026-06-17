# Python 脚本 (script/python)

## 用法

- 定义脚本，不自行运行；输出 script 连接到 script/exec。
- 适合把多个视觉查找、点击、变量读写或结果计算封装成一段可复用逻辑。
- 通过 Python 执行节点动态添加入参和结果端口，在代码中读取入参并写出结果。
- 按住快捷键类操作应优先使用上下文管理器写法，确保异常时也会释放按键。

## AI 搭建推荐模式

- 简单点击、等待、OCR、断言优先保持为可视化节点；脚本只用于循环、重复动作、组合判断、变量计算或图连线会明显复杂的场景。
- 通过 `get_arg('name')` 读取 `script/exec` 动态入参。设备、模板图片、mask、OCR、文本、数值、布尔值都应从图上接入。
- 用 `set_result('ok', bool)` 输出业务判断结果，再把 `ok` result 连接到 `assert/check` 和 `test/result`。
- 不要在 AI 生成脚本中使用文件、网络、系统命令、`subprocess`、`eval`、`exec` 或安装依赖。

```python
dev = get_arg('dev')
button = get_arg('button')

match = dev.wait_appear(button, timeout=10)
if match:
    dev.click(to_point(match))

set_result('ok', match is not None)
```
