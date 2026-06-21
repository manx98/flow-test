# 表单序列化

把对象或键值对列表序列化为 `application/x-www-form-urlencoded` 文本。

## 使用建议

- 常用于生成表单 POST 请求的 body。
- value 输入可以接脚本输出的 dict，或 value 属性填写 JSON 对象。
- 生成后接 `api/request.body`，并把请求节点 content_type 设置为 `application/x-www-form-urlencoded; charset=utf-8`。
- doseq=true 时，数组值会展开为重复 key，例如 `a=1&a=2`。
