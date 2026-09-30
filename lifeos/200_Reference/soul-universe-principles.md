# Soul Universe 產品原則

> 來源：《Soul Universe｜AI Context File 完整產品設計與 Claude 交接文件》（2026-09-29）
> **Agent 不可自行改寫這份。** 要改由我手動改。

## 版本基準

- 本產品線使用 **64 型系統**，不是 72 型
- 舊資料若出現「72 型」視為舊稱，不得沿用

## 十條不可改動的原則

1. Soul Universe 不是恐嚇式算命
2. 不替使用者決定人生
3. 品牌角色是「同行者，不是老師」
4. 多系統的價值在交叉後的共同／互補／張力，不在系統數量
5. 不把歷史人物／老師名字放進輸出
6. 不把類型代碼大量展示給一般使用者
7. 沒有資料就寫「待補」，不要發明
8. 不要為了 AI Context 重新發明一套人格系統
9. 先使用現有 Soul Universe 的結果與規則
10. 第一版務必小，不要做成完整 AI SaaS

## 對外核心概念

> 你的靈魂使用說明書 / Understand yourself. Choose your path.

## 文案語氣

| 不要寫 | 改成 |
|---|---|
| 根據你的命盤，你就是…… | 你的結果反覆顯示一個可能的傾向…… |
| 你天生就是／你不適合 | 在幾個不同角度裡，都出現類似訊號…… |
| （斷定語氣） | 你可以看看這是否符合你的真實經驗。 |
| （把測驗當永久結論） | 如果現在的你已經不同，請以現在的自己為準。 |

## 來源標記規則

任何產出都要能區分三層，不可混為一談：

- `【已驗證外部來源】` — 附網址與查證日期
- `【Soul Universe 內部既有規則】`
- `【產品設計推論】`

無法驗證的外部對標 → 標「待重新驗證」，不得寫成「市場已證實」。

## 隱私

輸出只放**已蒸餾過、有使用價值的描述**。預設不輸出：
真實姓名、完整出生地址、身分證件、電話、家人姓名、非必要的精確出生時間。

## 待辦（來自交接文件的任務 1–5）

- [ ] `Soul-Context-Schema-v1.md`
- [ ] `Soul-Context-Free-Renderer-v1.md`
- [ ] `Soul-Context-Full-Product-v1.md`
- [ ] `Soul-Context-MVP-Spec-v1.md`
- [ ] Conversion tracking 事件定義（`context_view` / `context_copy` / `context_download` / `full_context_click` / `full_context_purchase`）
