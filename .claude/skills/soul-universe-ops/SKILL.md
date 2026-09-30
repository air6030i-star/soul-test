---
name: soul-universe-ops
description: Soul Universe 網站維運——改頁面、調定價、加功能、修連結、部署前檢查。當使用者要動 index.html / couple / parenting / workplace / delivery / soulfinder 這些頁面時使用。走 F・自有產品。
---

# soul-universe-ops｜網站維運

走 `lifeos/000_Agent/routes/F_自有產品.md`，並先讀 `lifeos/200_Reference/soul-universe-principles.md`。

## 動手前

1. **先寫「這次不做什麼」**（F 路線第 1 步）
2. 讀根目錄 `CLAUDE.md` 的「Soul Universe 網站」段
3. 跑 `.claude/skills/seo-check` 取得改動前的基準

## 網站結構

| 檔案 | 線 |
|---|---|
| `index.html` | 主入口，64 型免費測驗（14 題） |
| `couple.html` / `couple-quiz.html` / `couple-download.html` | 情侶 |
| `parenting.html` | 親子 |
| `workplace.html` / `workplace-download.html` | 職場 |
| `delivery.html` | 交付 |
| `soulfinder/index.html` | 選鏡子引導（4 題） |

## 硬規則

- **單檔 HTML，CSS/JS 內嵌。** 不要拆檔、不要引入 build tool、不要加 npm。
- **UTF-8。** 編輯後一定要確認中文正常，歷史上出過雙重編碼亂碼。
- **改定價／頁數／連結 → 先 `grep` 全站**：
  ```bash
  grep -n 'NT\$\|US\$' *.html soulfinder/*.html
  ```
  一次改完所有出現處，包含 FAQ 區塊（過去漏改過）。
- 文案語氣受 `soul-universe-principles.md` 約束，不可寫斷定式命理語句。

## 改完之後

```bash
bash lifeos/scripts/health-check.sh      # 跟改動前的基準比對
git diff --stat
```

確認：
- [ ] 中文沒有變亂碼
- [ ] 定價全站一致
- [ ] 內部連結都指得到
- [ ] 沒有動到不該動的頁面

## 紅線

- **不自動 push、不自動部署。** 這是已上線的正式站，commit 與 push 由使用者決定。
- 不要「順手」重構或美化沒被要求改的部分。
