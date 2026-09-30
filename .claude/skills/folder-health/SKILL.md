---
name: folder-health
description: Life OS 資料夾體檢——檢查命名規則、卡住的案子、該封存沒封存的、inbox 積壓、隱私外洩風險。當使用者說「資料夾體檢」「整理一下」「檔案好亂」時使用。
---

# folder-health｜資料夾體檢

## 執行

```bash
bash lifeos/scripts/folder-health.sh
```

## 六項檢查

### 1. 隱私（最優先）

確認 `lifeos/100_Todo/`、`300_Journal/`、`200_Reference/private/` 底下沒有檔案被 git 追蹤：

```bash
git ls-files lifeos/100_Todo lifeos/300_Journal lifeos/200_Reference/private
```

**除了 `.gitkeep` 與 `private/README.md` 以外有任何輸出，就是外洩，要立刻處理。**
這個 repo 是 public。

### 2. 命名規則

對照 `lifeos/000_Agent/04_命名與檔案規則.md`：

- 日期一律 `YYYY-MM-DD`
- 檔名沒有空白
- 檔名沒有 `最新` / `final` / `v3` 這類狀態字
- 沒有全形標點

### 3. Frontmatter 完整性

`100_Todo/projects/` 每個檔案都要有 `路線 / 狀態 / 對象 / 截止 / 預估工時 / 實際工時`。
`狀態` 只能是：`待開始` `進行中` `等對方` `完成` `取消`。

### 4. 該封存沒封存

`狀態: 完成` 或 `取消` 但還留在 `100_Todo/projects/` → 列出來，建議走 `memory-writeback`。

### 5. 卡住的案子

- `狀態: 等對方` 超過 7 天
- `狀態: 進行中` 但最後一筆記錄超過 14 天

→ 列出來並問：追 / 再等 / 放掉。

### 6. Inbox 積壓

`100_Todo/inbox/` 超過 5 個 `#待分流` → 提出來，建議排一次集中分流。

## 輸出

```
資料夾體檢 <YYYY-MM-DD>

[隱私] <通過 / 問題清單>
[命名] <N> 個不符合：<清單>
[欄位] <N> 個缺欄位：<清單>
[待封存] <清單>
[卡住] <清單，含天數與建議>
[Inbox] <N> 件待分流

建議動作（最多 3 項）：
1.
```

## 紅線

- **只回報與建議，不自動移動或改名檔案。** 要動就出草案等確認。
- 隱私項目如果不通過，**先講這一項，其他都往後排**。
