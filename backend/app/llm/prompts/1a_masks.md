# 几何蒙版识别（1A.masks）

你看到的是一段视频中某个 scene 的中间帧。请判断画面中**是否存在几何蒙版**（圆形 / 矩形 / 直线分屏 / 半透明遮罩等），并给出参数。按以下 JSON Schema 输出。

## 输出 JSON Schema

```json
{{
  "has_mask": bool,
  "kind": "circle" | "rectangle" | "line_split" | null,
  "params_norm_0_999": {{
    "circle": {{ "cx": int, "cy": int, "radius": int }},
    "rectangle": {{ "x": int, "y": int, "w": int, "h": int }},
    "line_split": {{ "x1": int, "y1": int, "x2": int, "y2": int, "side_kept": "left" | "right" | "top" | "bottom" }}
  }} | null,
  "confidence": 0.0-1.0,
  "reasoning": "≤200 字中文解释"
}}
```

## 判定规则

- `circle`：画面中有一个明显的圆形 / 椭圆形 mask（如圆形头像、圆形 vignette）。
- `rectangle`：画面中有一个矩形 mask 包裹画面主体（小窗、画中画）。
- `line_split`：画面被一条直线（水平 / 垂直 / 倾斜）分成两部分，一侧是主画面，另一侧是别的东西（背景色 / 模糊 / 第二画面）。
- `has_mask=false` 时 `kind=null`、`params_norm_0_999=null`。

## 关键约束

- 自然画面边界（黑边 letterbox、上下黑条）**不算**几何蒙版。
- 仅在 `has_mask=true` 时填充 `params_norm_0_999` 中对应 kind 的参数；其余 kind 字段填 null 或省略。
