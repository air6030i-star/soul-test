# CLAUDE.md

這個 repo 有兩個身分，進來先分清楚你現在在做哪一件事。

## 1. Soul Universe 網站（本 repo 的主體）

根目錄的 HTML 是**已上線的正式網站**（GitHub Pages，public）：

| 檔案 | 用途 |
|---|---|
| `index.html` | 主入口，64 型靈魂密碼免費測驗（14 題） |
| `couple.html` / `couple-quiz.html` / `couple-download.html` | 情侶線 |
| `parenting.html` | 親子線 |
| `workplace.html` / `workplace-download.html` | 職場線 |
| `delivery.html` | 交付頁 |
| `soulfinder/index.html` | 選鏡子引導（4 題） |

改這些檔案的規則：

- 這些是**單檔 HTML**，CSS/JS 內嵌。不要為了「比較乾淨」拆檔或引入建置工具。
- 檔案是 UTF-8。過去出過**雙重 UTF-8 亂碼**事故，編輯後務必確認中文顯示正常。
- **定價、頁數、連結**散落在多個頁面，改一處就要全站同步（歷史 commit 有多次「定價同步」「FAQ 移除過時定價」的修補）。改價前先 `grep` 全站。
- 產品原則見 `lifeos/200_Reference/soul-universe-principles.md`，那份不可自行改寫。

## 2. Life OS（`lifeos/`）

這是本人的一人公司作業系統。所有「一件事進來該怎麼走」的規則都在 `lifeos/000_Agent/`。

**收到任何工作請求時，先讀 `lifeos/000_Agent/01_分流判斷.md`，判斷它屬於 A–F 哪一條路線，再照那條路線的 SOP 走。**

核心檔案：

- `lifeos/000_Agent/00_身份與邊界.md` — 我是誰、你能替我做什麼、不能替我做什麼
- `lifeos/000_Agent/01_分流判斷.md` — 分流判斷表（**每次都先讀這份**）
- `lifeos/000_Agent/02_記憶回寫.md` — 事情做完後寫回哪裡
- `lifeos/000_Agent/03_草案協定.md` — 草案編號、有效期、確認流程
- `lifeos/000_Agent/04_命名與檔案規則.md` — 檔案放哪、怎麼命名
- `lifeos/000_Agent/routes/` — A–F 六條路線各自的實際步驟

## 3. 絕對不要 commit 的東西

`lifeos/` 底下這些資料夾的內容**永遠留在本機**，`.gitignore` 已經擋住，不要用 `git add -f` 繞過：

- `lifeos/100_Todo/` — 進行中的案子、客戶、報價
- `lifeos/300_Journal/` — 日誌
- `lifeos/200_Reference/private/` — 私人參考資料
- 任何含真實姓名、電話、地址、金額、合約、客戶名單的檔案

**這個 repo 是 public。** 寫任何檔案前先問自己：這段文字被陌生人看到會有問題嗎？會，就不要寫進 git。

## 4. Skills

`.claude/skills/` 底下有 10 個常用工作的 skill。使用者說「幫我排今天的事」「這篇幫我寫」「這個月帳整理一下」時，先看有沒有對應 skill。
