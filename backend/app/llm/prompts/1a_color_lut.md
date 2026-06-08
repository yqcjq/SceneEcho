# 调色语义识别（1A.color_lut）

你看到的是一段视频的三张采样帧（首 / 中 / 末）。请按以下 JSON Schema 给出主观调色标签 + dominant LUT 推荐（从给定库里选一个最像的）。

## 输出 JSON Schema

```json
{{
  "tags": ["暖色" | "冷色" | "高饱和" | "低饱和" | "电影感" | "平淡"],
  "dominant_lut_id": "<LUT 库里的 id>",
  "confidence": 0.0-1.0,
  "reasoning": "≤200 字中文解释"
}}
```

## tags 多选规则

- `暖色 / 冷色`：互斥；以画面主导色温（橙黄 vs 蓝青）判断。
- `高饱和 / 低饱和`：互斥；高饱和色彩鲜艳，低饱和接近灰阶。
- `电影感`：高对比 + 略 desaturated + 阴影偏蓝青。
- `平淡`：无明显风格，接近原片。
- 多选合理（如「暖色 + 高饱和」），但不超过 4 个标签。

## dominant_lut_id

从用户提供的 LUT 库（`data/system/luts/luts_index.json`）中选 id；如果传入的 LUT library 信息为空或无明显匹配，给 `"none"`。

## 关键约束

- 不要被人物 / 主体颜色误导，看画面整体色调。
- LUT 库的具体 id 由调用方在 prompt 里追加传入；保持你的判断与 tags 一致。
