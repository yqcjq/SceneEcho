# 缩放方向粗判（1A.zoom_direction）

你看到的是一段镜头内三张采样帧（首 / 中 / 末），左上角带 "first" / "mid" / "last" 标识。请判断**这一镜头内**画面缩放（zoom）的整体方向，按以下 JSON Schema 输出。

## 输出 JSON Schema

```json
{{
  "direction": "推进" | "拉远" | "稳定" | "抖动",
  "confidence": 0.0-1.0,
  "reasoning": "≤200 字中文解释，引用三帧画面差异"
}}
```

## 判定规则

- `推进`：last 帧主体在画面中占比明显大于 first（zoom in）。
- `拉远`：last 帧主体占比小于 first（zoom out）。
- `稳定`：三帧视野范围基本不变，仅有微小晃动 / 物体内部移动。
- `抖动`：缩放剧烈反复（first→mid 推进 mid→last 拉远等），无明确方向。

## 关键约束

- 不要被画面内的物体移动 / 人物动作误导——focus 镜头视角变化（视野广角 vs 局部）。
- `confidence < 0.6` 时倾向标 `稳定`，让下游 CV 用光流验证细节。
