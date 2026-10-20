# 模型选择指南

> 本文档由构建系统自动生成（数据源：`budget-models.json`），请勿手改。
> 三档预设体现「免费优先 → 平衡 → 质量优先」的成本梯度；档位切换：`budget setup agent preset <economic|balanced|quality>`。

## 模型目录

{{models_table}}

## 预设总览（三档 × 全部平台）

{{preset_table}}

## 平台说明

{{platform_note}}

## 使用建议

- **默认档位为 balanced**：构建期 agent 产物的 `model` 字段按 balanced 预设烘焙，覆盖全部 10 个角色。
- **成本梯度不可倒挂**：coder_senior > coder_standard > coder_lite（任何预设均满足）。
- **审查与编码尽量不同厂商**：减少「自己写自己审」的同系盲区。
- **简写别名**：`budget setup agent custom <alias>` 支持简写（如 `opus`/`kimi`/`glm`），自动解析为标准 ID 后统一覆写。
- **待确认标注**：各平台未能核对的 provider/model ID 在 `budget-models.json` 的 `platforms.<平台>.unconfirmed_ids` 中列出，上线前须逐一核对清零。
