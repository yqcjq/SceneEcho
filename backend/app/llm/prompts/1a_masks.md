# 几何蒙版识别（1A.masks）

你看到的是一段视频中某个 scene 的若干采样帧。请判断画面中**是否存在几何蒙版**——给画面整体形状包装的几何区域（圆形头像框、矩形画框、线分屏、半透明遮罩），并按以下 JSON Schema 输出。

> **重要边界（必读）**：以下元素**不算几何蒙版**，请直接忽略，不要写入 `has_mask=true`：
> - **字幕** / 字幕底色块 / 字幕带描边
> - **标题条** / 顶栏 / 底栏 UI bar
> - **水印** / 平台 logo / 小窗口 logo
> - **贴纸** / 装饰图标
> - **UI 元素**：按钮、进度条、计时器、点赞数等界面控件
> - **画面自身边界**：letterbox 黑边、上下黑条、画布边框
>
> 几何蒙版的核心特征是「**对画面主体进行形状包装**」——画面被一个明确的几何区域裁切，区域之外是另一种内容（背景色 / 模糊版 / 第二画面）。

## 输出 JSON Schema

```json
{
  "has_mask": bool,
  "kind": "circle" | "rectangle" | "line_split" | null,
  "params_norm_0_999": {
    "circle": { "cx": int, "cy": int, "radius": int },
    "rectangle": { "x": int, "y": int, "w": int, "h": int },
    "line_split": { "x1": int, "y1": int, "x2": int, "y2": int, "side_kept": "left" | "right" | "top" | "bottom" }
  } | null,
  "confidence": 0.0-1.0,
  "reasoning": "≤200 字中文解释"
}
```

## 判定规则

- `circle`：画面中有一个明显的圆形 / 椭圆形 mask（如圆形头像、圆形 vignette），mask 外是背景色 / 模糊画面。
- `rectangle`：画面被一个矩形区域包裹（小窗、画中画、边框），矩形外是另一画面 / 装饰背景。**纯字幕底色块、UI bar、广告位不算**。
- `line_split`：画面被一条直线（水平 / 垂直 / 倾斜）切成两半，一侧是主画面，另一侧是别的东西（背景色 / 模糊 / 第二画面 / 静态图）。
- `has_mask=false` 时 `kind=null`、`params_norm_0_999=null`。**默认倾向 false**——若不确定是真几何蒙版还是字幕 / UI / 边框，请填 false。

## 关键约束

- 自然画面边界（黑边 letterbox、上下黑条）**不算**几何蒙版。
- 仅在 `has_mask=true` 时填充 `params_norm_0_999` 中对应 kind 的参数；其余 kind 字段填 null 或省略。
- `confidence < 0.6` 时倾向标 `has_mask=false`——demo 阶段对漏报的容忍度大于对误报的容忍度（误报会让模板复用时叠加假蒙版，体感差于"识别不到"）。
