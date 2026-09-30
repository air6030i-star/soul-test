# 雙 AI 會診台（Claude × ChatGPT）

讓 Claude 和 ChatGPT 針對同一個題目／案件輪流討論，你在瀏覽器當主持人：選討論方式、看它們對話、隨時插話提問，讓它們繼續討論。

- 用本機已登入的 `claude`（Claude Code）與 `codex`（ChatGPT Codex CLI），扣各自訂閱額度，不需 API key。
- 只用 Python 標準函式庫，不用安裝套件。
- 完整說明見 [SKILL.md](SKILL.md)。

## 快速開始

```bash
# 1. 安裝並登入兩個 CLI（各做一次）
npm install -g @anthropic-ai/claude-code   && claude     # 登入 Claude
npm install -g @openai/codex               && codex login # 登入 ChatGPT

# 2. 先用模擬模式看介面（不耗額度）
python debate.py --mock

# 3. 正式使用
python debate.py "D:\案件\王小明租約"
```

Windows 可執行一次 `python install_context_menu.py`，之後在資料夾按右鍵 →「雙 AI 會診」即可開啟；或把資料夾拖到 `雙AI會診.bat` 上。

## 檔案

| 檔案 | 用途 |
|---|---|
| `debate.py` | 主持台（本機網頁伺服器＋呼叫兩個 AI） |
| `SKILL.md` | 給 Claude Code 的 skill 說明（可複製到 `~/.claude/skills/ai-debate/`） |
| `雙AI會診.bat` | Windows 拖放啟動 |
| `install_context_menu.py` | Windows 右鍵選單安裝／移除 |
