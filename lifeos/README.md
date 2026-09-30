# Life OS

一人公司的作業系統。Claude Code 與 Codex 共用同一套規則與同一個資料夾。

## 兩層架構

| 層 | 內容 | 進 git？ |
|---|---|---|
| **規則層** | `000_Agent/`、`200_Reference/`（根層）、`scripts/`、`.claude/skills/` | ✅ 進，可公開、可攜 |
| **資料層** | `100_Todo/`、`300_Journal/`、`900_Archive/`、`200_Reference/private/` | ❌ 不進，留在本機 |

> **這個 repo 是 public + GitHub Pages。** 資料層只要進 git 就是公開。
> `.gitignore` 已經擋住，`folder-health` 每次會再驗一遍。

## 一件事怎麼走完全程

```
起點 → 分流判斷 → A / B / C / D / E / F → 記憶回寫 → 封存
```

| 路線 | 進入條件 |
|---|---|
| **A・每週例行** | 每週/每月固定會再發生 |
| **B・臨時插單** | 有外部期限且在 72 小時內 |
| **C・內容創作** | 產出是要對外發佈的內容 |
| **D・接案與內訓** | 客戶是別人 |
| **E・財務管理** | 會產生收入或動用金錢 |
| **F・自有產品** | 以上皆非，是我自己想做的 |

判斷表在 `000_Agent/01_分流判斷.md`，**由上往下比對，第一個命中的就是答案**。

## 核心約定

1. **Agent 產出的一切都先是草案。** 沒說「確認」就不執行、不對外送出。（`000_Agent/03_草案協定.md`）
2. **沒有依據就寫「待補」。** 不推測、不生成看起來很像真的的假資料。
3. **記憶隨生隨寫，不等結束。** 取消的事也要寫原因。
4. **Agent 不對外送出任何東西。** 不發文、不寄信、不回訊息、不付款。

## 開始使用

```bash
# 1. 跑上線訪談，把 00_身份與邊界.md 的「待補」補完（約 10 分鐘）
#    在 Claude Code 說：「跑 onboarding 訪談」

# 2. 資料夾體檢
bash lifeos/scripts/folder-health.sh

# 3. 網站健檢（Soul Universe）
bash lifeos/scripts/health-check.sh
```

## Skills（`.claude/skills/`）

| Skill | 什麼時候用 |
|---|---|
| `task-intake` | 一件事進來，要分流建檔 |
| `daily-briefing` | 開工，今天先做哪一件 |
| `weekly-review` | 週回顧、下週規劃、趨勢 |
| `content-draft` | 寫貼文／長文／腳本 |
| `client-proposal` | 接案詢價、報價 |
| `finance-log` | 記帳、月結、應收、訂閱體檢 |
| `memory-writeback` | 收尾、封存 |
| `seo-check` | 網站健檢 |
| `soul-universe-ops` | 改 Soul Universe 頁面 |
| `folder-health` | 資料夾體檢 |

## 給 Codex / 其他 agent

讀根目錄 `AGENTS.md`。規則的唯一真相來源是 `CLAUDE.md`，兩邊不另立一套。

## 搬去獨立 vault

這套設計成可以整包搬走。複製 `lifeos/` 與 `.claude/skills/` 到新資料夾即可；
需要調整的只有 `CLAUDE.md` 裡「Soul Universe 網站」那一段，以及
`scripts/health-check.sh`（那份是綁本 repo 網站的）。

Obsidian 直接把 `lifeos/` 開成 vault 就能用，Markdown 沒有相依。
