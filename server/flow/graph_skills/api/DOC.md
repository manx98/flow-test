# API

API 模块用于在测试流程中发送 HTTP 请求，并把响应状态、响应正文和成功标记传给后续节点。

## 使用建议

- 适合调用被测系统的准备接口、查询接口、清理接口，或在 UI 操作前后校验后端状态。
- URL、headers、body 可以写在节点属性中；需要运行时拼接或复用时，优先用文本常量、变量或脚本输出接入对应输入口。
- 响应正文输出为文本；需要解析 JSON 或复杂判断时，把 body 传给 JS 脚本节点处理，再输出 bool 接断言。
- JSON 请求体优先用 JSON输入节点生成，再连接 HTTP 请求或脚本。
- 表单请求体使用表单序列化节点生成 `application/x-www-form-urlencoded` 文本，并把 HTTP 请求的 content_type 设置为 `application/x-www-form-urlencoded; charset=utf-8`。
- 敏感 token 不建议硬编码到流程文件里；优先由外部配置或运行时输入传入。
- 网络请求可能受运行环境网络、代理、证书和目标服务状态影响，失败时优先查看 status 与 body 输出。
