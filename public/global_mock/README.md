# public/global_mock/ — 全局可自定义 Mock

> Mock 机制三原则之三（rules-3 §四）：可覆盖——开发者可自定义本目录下的 Mock 实现覆盖默认值，适配特殊测试场景。

## 当前状态：未生成

本目录当前为空，待 `pre_generated_mock/` 生成后，开发者按需创建覆盖 Mock。

## 使用方式

1. `pre_generated_mock/` 提供默认 Mock 实现
2. 开发者在 `global_mock/` 下创建同名文件覆盖默认 Mock
3. 测试框架优先加载 `global_mock/`，回退到 `pre_generated_mock/`

## 切换路径：Mock → 真实实现

模块开发完成后，调用方只需修改导入路径，代码无需其他改动（rules-3 §四）。
