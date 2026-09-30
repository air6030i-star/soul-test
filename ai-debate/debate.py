#!/usr/bin/env python3
"""
雙 AI 會診 / 討論主持台 (debate.py)

讓本機已登入的 Claude Code (claude -p) 與 ChatGPT Codex CLI (codex exec)
輪流發言、互相回應；你在瀏覽器當主持人：選討論方式、看它們對話、隨時插話、
要它們下結論，或結束後再提問讓它們繼續討論。

用量分別扣 Claude 與 ChatGPT 的訂閱額度，不走 API、不另外產生 API 費用。
只用 Python 標準函式庫，不需安裝任何套件。

用法：
    python debate.py [案件資料夾] [--port 8765] [--mock] [--no-browser]

    案件資料夾：選填。兩個 AI 會在這個資料夾內「唯讀」查閱檔案；
               所有產出寫到 <案件資料夾>/_AI會診/ 底下，原檔一律不動。
    --mock    ：不呼叫真的 AI，用假回覆測試介面與流程。
"""

import argparse
import datetime as dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

OUT_DIR_NAME = "_AI會診"
AI_TIMEOUT = int(os.environ.get("DEBATE_TIMEOUT", "900"))
MAX_TRANSCRIPT_CHARS = 40000
IGNORED_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}

# ---------------------------------------------------------------------------
# 參與者（兩個 AI）
# ---------------------------------------------------------------------------

AGENTS = {
    "claude": {"name": "Claude", "vendor": "Anthropic"},
    "chatgpt": {"name": "ChatGPT", "vendor": "OpenAI"},
}


class CLIError(RuntimeError):
    """呼叫 claude / codex 失敗，訊息是給主持人看的中文說明。"""


def _split_cmd(env_key, default):
    return shlex.split(os.environ.get(env_key, default), posix=(os.name != "nt"))


_TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z?\s+")
_COUNT_RE = re.compile(r"\b\d+/\d+\b")


def tidy_output(text, keep_lines=15, limit=1200):
    """把 CLI 輸出收斂成可讀的錯誤訊息。

    codex 連不上時會把同一行（只差時間戳與重試次數）刷幾十次，直接截尾會只看到雜訊。
    這裡去掉時間戳與「2/5」之類的計數後去重，只保留最後幾行不同的內容。
    """
    seen, keep = set(), []
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line:
            continue
        key = _COUNT_RE.sub("N/N", _TS_RE.sub("", line))
        if key in seen:
            continue
        seen.add(key)
        keep.append(line)
    return "\n".join(keep[-keep_lines:]).strip()[-limit:]


def _as_text(data):
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data or ""


def run_cli(cmd, prompt, workdir, label, timeout=None):
    """共用的 CLI 呼叫：提示詞走 stdin，逾時與找不到指令都給明確訊息。"""
    # DEBATE_*_CMD 可能寫成完整路徑（Windows 上還可能帶引號），所以先脫引號再找。
    raw = cmd[0].strip('"').strip("'")
    exe = shutil.which(raw) or (raw if os.path.isfile(raw) else None)
    if not exe:
        raise CLIError(f"找不到 {cmd[0]} 指令。請先安裝並登入 {label}，"
                       f"或用 --mock 試跑介面。")
    # 用絕對路徑呼叫；Windows 上 npm 裝的是 claude.cmd / codex.cmd，仍需要 shell 才能執行。
    cmd = [exe] + list(cmd[1:])
    secs = timeout or AI_TIMEOUT
    try:
        return subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=workdir, timeout=secs,
            shell=(os.name == "nt"),
        )
    except subprocess.TimeoutExpired as e:
        # 逾時的時候 CLI 通常已經把真正的原因（例如未登入、連不上）寫到 stderr 了，
        # 一併帶出來，不然只看到「逾時」完全不知道要修什麼。
        # 注意 TimeoutExpired.stderr 在 POSIX 上是 bytes、在 Windows 上是 str。
        detail = tidy_output(_as_text(e.stderr) or _as_text(e.stdout))
        raise CLIError(
            f"{label} 超過 {secs} 秒沒有回應。常見原因：尚未登入、額度用盡、網路不通。"
            f"（可用環境變數 DEBATE_TIMEOUT 加長逾時秒數）"
            + (f"\n它在逾時前印出的訊息：\n{detail}" if detail else "")
        ) from None


def call_claude(prompt, workdir, timeout=None):
    """claude -p：非互動模式，只允許讀檔類工具（已實測：寫檔會被拒絕）。"""
    cmd = _split_cmd("DEBATE_CLAUDE_CMD", "claude -p --output-format text")
    cmd += ["--allowedTools", "Read", "Grep", "Glob"]
    proc = run_cli(cmd, prompt, workdir, "Claude Code", timeout)
    text = (proc.stdout or "").strip()
    if proc.returncode != 0:
        raise CLIError(f"claude 執行失敗（結束碼 {proc.returncode}）：\n"
                       + (tidy_output(proc.stderr) or tidy_output(proc.stdout) or "沒有錯誤訊息"))
    if not text:
        detail = tidy_output(proc.stderr)
        raise CLIError("claude 沒有回覆任何內容。"
                       + (f"\n錯誤輸出：\n{detail}" if detail else "請執行 --check 確認登入狀態。"))
    return text


def call_codex(prompt, workdir, timeout=None):
    """codex exec：唯讀沙盒，最後一則訊息寫到暫存檔再讀回。

    注意 codex 會把橫幅與進度寫到 stderr，正式回覆只在 --output-last-message 指定的檔案裡，
    所以空白檔案要當成失敗，不能當成「AI 沒話說」。
    """
    fd, last_msg = tempfile.mkstemp(suffix=".txt", prefix="codex_")
    os.close(fd)
    try:
        cmd = _split_cmd("DEBATE_CODEX_CMD", "codex exec")
        cmd += ["--sandbox", "read-only", "--skip-git-repo-check",
                "--output-last-message", last_msg, "-"]
        proc = run_cli(cmd, prompt, workdir, "ChatGPT Codex CLI", timeout)
        text = Path(last_msg).read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            text = (proc.stdout or "").strip()   # 舊版沒有 --output-last-message 時的退路
        if not text:
            raise CLIError(f"codex 沒有回覆任何內容（結束碼 {proc.returncode}）：\n"
                           + (tidy_output(proc.stderr) or tidy_output(proc.stdout) or "沒有錯誤訊息"))
        return text
    finally:
        try:
            os.remove(last_msg)
        except OSError:
            pass


def call_mock(agent, prompt):
    time.sleep(1.2)
    if "【分歧整理】" in prompt.rsplit("【本輪任務】", 1)[-1]:
        return ("## 共同認同\n- 產品格式需要簡化\n## 主要分歧\n1. 〈先做哪種格式〉\n   - Claude：Notion 版\n"
                "   - ChatGPT：電子書版\n   - 核心假設：是否已有穩定流量\n   - 需要什麼資料才能判斷：現有轉換率")
    task = prompt.rsplit("【本輪任務】", 1)[-1].strip().splitlines()[0][:60]
    host = re.findall(r"\[主持人\] (.+)", prompt)
    extra = f"\n\n回應主持人：「{host[-1][:40]}」——這點我同意要優先處理。" if host else ""
    return (f"（{AGENTS[agent]['name']} 模擬發言）針對「{task}」，我的看法有三點：\n"
            f"1. 先釐清前提。\n2. 列出證據與反例。\n3. 提出可執行的下一步。{extra}")


def ask(agent, prompt, workdir, mock, timeout=None):
    if mock:
        return call_mock(agent, prompt)
    if agent == "claude":
        return call_claude(prompt, workdir, timeout)
    return call_codex(prompt, workdir, timeout)


# ---------------------------------------------------------------------------
# 討論方式
#   roles    : (先手角色, 後手角色)
#   blind    : 開場是否「各自閉卷」同時作答，看不到對方
#   opening  : 開場任務
#   debate   : 每輪任務（清單依輪次取用，超過則用最後一個）
#   closing  : 最終立場
#   synthesis: 由一方整合的結論格式（一律再附上 SYNTHESIS_RULES）
#   focus    : 是否在開場後整理「分歧」，之後每輪只討論這些分歧（預設 True）
# ---------------------------------------------------------------------------

MAX_ISSUES = 3
DEFAULT_CLOSING = "這是最後一輪。請用條列寫出你的最終立場：你同意對方的哪些點、仍然不同意哪些點、理由是什麼。"
DEFAULT_CROSSREAD = ("【互相閱讀】現在你看得到對方的獨立分析。請不要重寫自己的分析，而是：\n"
                     "1) 你同意對方的哪些點\n2) 你不同意或認為有錯的點與理由（有案件資料時回原檔查證並註明出處）\n"
                     "3) 對方提到而你漏掉的重點\n4) 你要修正自己原本的哪些地方")
DEFAULT_SYNTHESIS = ("請整合整場討論，格式如下：\n"
                     "## 共同認同\n## 仍有分歧（每點分別寫出 Claude 的立場與 ChatGPT 的立場）\n"
                     "## 造成分歧的核心假設\n## 缺乏的資料／建議補查\n## 可立即執行事項\n## 最大風險\n## 需要主持人決定的事")
SYNTHESIS_RULES = (
    "\n\n整合規則（務必遵守）：\n"
    "- 你是中立書記，不是裁判。不要替主持人做決定，也不要為了收尾而硬湊共識或寫「綜合兩方意見，建議 A」。\n"
    "- 只有雙方都明確同意的才能寫成共識；其餘一律放進「仍有分歧」，用兩方各自的原意寫出立場，並標明是 Claude 或 ChatGPT，"
    "不要偏袒你自己先前的立場。\n"
    "- 每個分歧都要寫出背後的核心假設：這個假設成立時偏向哪一方、要什麼資料才能驗證。\n"
    "- 「需要主持人決定的事」請寫成選擇題（例如：優先追求上市速度，還是互動性？），並說明各選項的代價。\n"
    "- 若上面指定的格式沒有「仍有分歧」與「需要主持人決定的事」，請在最後補上這兩節。")
ISSUES_TASK = (
    f"【分歧整理】請擔任中立書記（不是裁判），根據到目前為止雙方的發言，整理出真正的分歧，最多 {MAX_ISSUES} 個，依重要性排序。"
    "只列雙方看法實質不同的地方；用語不同但意思相同的不算。若主持人有補充新條件，請依新條件重新判斷。"
    "嚴格依照以下格式，不要加其他內容：\n"
    "## 共同認同\n（簡短條列）\n"
    "## 主要分歧\n1. 〈分歧標題〉\n   - Claude：…\n   - ChatGPT：…\n"
    "   - 核心假設：…（這個假設成立就偏向哪一方）\n   - 需要什麼資料才能判斷：…")
FOCUS_RULE = ("請只針對上面列出的分歧逐點回應（標明編號），已有共識的部分不要重講。"
              "若你被對方說服，請直接說「第 N 點我改變立場」；若主持人補充的條件改變了某個分歧，請直接指出。")

MODES = [
    {
        "key": "consult", "name": "會診（案件分析）",
        "desc": "各自閉卷讀資料 → 互相事實核對 → 整理爭點 → 只針對爭點討論 → 結構化結論。",
        "roles": ("分析師", "分析師"), "blind": True,
        "opening": ("請獨立完成初步分析（你看不到對方的答案）。若有案件資料，請實際開檔閱讀。"
                    "請產出：1) 資料清單 2) 時間軸 3) 關鍵事實摘錄（註明出處檔名）4) 目前狀況 5) 爭點 6) 資料缺口。"),
        "crossread": ("【事實核對】逐點檢查對方的初步分析，回原檔查證，指出對方讀錯的、漏讀的、推論過頭的地方"
                      "（註明出處），並修正你自己的錯誤。"),
        "debate": ["【議程討論】回應對方最新發言；若主持人有插話，請先回應主持人。"],
        "closing": DEFAULT_CLOSING, "synthesis": DEFAULT_SYNTHESIS,
    },
    {
        "key": "free", "name": "自由討論",
        "desc": "兩位輪流發表看法，互相補充與回應。",
        "roles": ("討論者", "討論者"), "blind": False,
        "opening": "請先對主題提出你的核心觀點與理由。",
        "debate": ["請回應對方的最新發言：補充、修正或提出不同看法，並推進討論。"],
        "closing": DEFAULT_CLOSING, "synthesis": DEFAULT_SYNTHESIS,
    },
    {
        "key": "debate", "name": "正反辯論",
        "desc": "先手為正方、後手為反方，各自堅守立場攻防。",
        "roles": ("正方（支持）", "反方（反對）"), "blind": True,
        "opening": "請發表立論：你的立場、三個最強論點與證據。",
        "debate": ["請反駁對方最新的論點，並強化自己的論證。不要輕易讓步，但也不能無視有效的反駁。"],
        "closing": "結辯：總結你方最有力的論點，並指出對方未能回應的弱點。",
        "synthesis": ("請整理辯論結果：\n## 正方最強論點\n## 反方最強論點\n## 雙方都承認的事實\n## 仍有分歧\n"
                      "## 造成分歧的核心假設\n## 哪些論點缺乏證據\n## 需要主持人決定的事"),
    },
    {
        "key": "business", "name": "商業評估",
        "desc": "一方看市場與收入、一方看成本與風險，逐項檢驗數字與假設。",
        "roles": ("市場與收入分析", "成本與風險分析"), "blind": True,
        "opening": ("請從你的角色獨立評估：目標客群與需求證據、競品與替代方案、定價與收入估算、"
                    "成本（時間／金錢／人力）、主要風險。所有數字都要寫出估算依據；沒有證據的請標註「假設」。"),
        "crossread": ("【互相閱讀】檢查對方的數字與假設：哪些有依據、哪些只是假設、哪些明顯高估或低估。"
                      "再補上對方從他的角度沒看到、但從你的角度很重要的因素。"),
        "debate": ["請回應對方最新發言。能用數字就用數字；對「假設」要提出最便宜、最快的驗證方式。"],
        "closing": "請寫出你的最終評估：做／不做／有條件做（條件是什麼），以及你最沒把握的一個假設。",
        "synthesis": ("請整合商業評估：\n## 評估總表（市場／收入／成本／風險：每項寫出雙方看法與依據）\n"
                      "## 關鍵假設與最便宜的驗證方式\n## 情境比較（樂觀／保守）\n## 共同認同\n## 仍有分歧\n"
                      "## 最大風險\n## 需要主持人決定的事"),
    },
    {
        "key": "execution", "name": "執行會議",
        "desc": "把方向拆成任務：一方規劃，一方檢查資源與時程，最後一定產出任務清單與下一步。",
        "roles": ("執行規劃者", "風險與資源檢查者"), "blind": False,
        "opening": ("執行規劃者：把目標拆成具體任務，每項寫出負責人、期限、完成標準。"
                    "負責人只能是「主持人」「Claude」「ChatGPT」或「待指派」。"
                    "風險與資源檢查者：檢查規劃者的任務清單，指出時程不合理、資源不足、依賴關係錯誤與遺漏的任務。"),
        "debate": ["執行規劃者：依檢查意見修正任務清單。風險與資源檢查者：確認修正版，指出還剩下的問題。"],
        "closing": "請寫出你認為本週最該先做的一件事與理由，以及仍然不同意對方的地方。",
        "synthesis": ("請整理成會議紀錄：\n## 決議事項（只列雙方都同意的）\n"
                      "## 任務清單（表格：任務｜負責人｜期限｜完成標準｜依賴）\n## 本週第一步\n"
                      "## 仍有分歧\n## 風險與預防措施\n## 需要主持人決定的事"),
    },
    {
        "key": "review", "name": "提案＋審查",
        "desc": "先手提出方案，後手專門審查找問題，先手再修正。",
        "roles": ("提案者", "審查者"), "blind": False,
        "opening": "提案者：請提出具體方案（步驟、理由、預期結果）。審查者：請審查提案者的方案，列出問題、風險與遺漏，依嚴重程度排序。",
        "debate": ["提案者：根據審查意見修正方案，說明改了什麼、哪些不改及原因。審查者：審查修正版，確認哪些問題已解決、還剩哪些。"],
        "closing": DEFAULT_CLOSING,
        "synthesis": ("請整合出最終版本：\n## 最終方案（只納入雙方都同意的部分）\n## 已解決的問題\n"
                      "## 仍有分歧\n## 仍存在的風險\n## 執行前待確認事項\n## 需要主持人決定的事"),
    },
    {
        "key": "brainstorm", "name": "腦力激盪",
        "desc": "先發散想點子、互相接龍延伸，最後收斂排序。",
        "roles": ("創意發想者", "創意發想者"), "blind": True, "focus": False,
        "opening": "請提出至少 5 個不同方向的點子，越多元越好，先不要批評。",
        "debate": ["請在對方的點子上接龍延伸或組合出新點子（至少 3 個），再挑出你覺得最有潛力的一個說明原因。"],
        "closing": "請從所有點子中選出你心中的前三名，並說明評估標準（可行性、效益、成本）。",
        "synthesis": "請收斂整場發想：\n## 點子總表（分類）\n## 推薦前三名與理由\n## 第一步可以怎麼做",
    },
    {
        "key": "devil", "name": "魔鬼代言人",
        "desc": "先手提出看法，後手專門唱反調、挑戰每個假設。",
        "roles": ("主張者", "魔鬼代言人（專門質疑）"), "blind": False,
        "opening": "主張者：請提出你的看法與依據。魔鬼代言人：請找出其中最脆弱的假設、反例與最壞情況。",
        "debate": ["請回應對方最新發言。主張者要補強或修正；魔鬼代言人要繼續追問最弱的環節。"],
        "closing": DEFAULT_CLOSING,
        "synthesis": "請整理：\n## 經得起挑戰的論點\n## 被推翻或需修正的論點\n## 關鍵假設與驗證方式\n## 建議",
    },
    {
        "key": "socratic", "name": "蘇格拉底詰問",
        "desc": "以提問為主，一層層追問定義、前提與推論，逼近問題本質。",
        "roles": ("詰問者", "回答者"), "blind": False, "focus": False,
        "opening": "詰問者：請先提出 2～3 個釐清定義與前提的問題。回答者：請認真回答詰問者的問題。",
        "debate": ["詰問者：針對回答中的模糊處或矛盾繼續追問。回答者：回答並承認被問倒的地方。"],
        "closing": "請各自說明：經過詰問後，你對這個主題的理解有什麼改變？",
        "synthesis": "請整理：\n## 釐清後的核心問題\n## 已確認的前提\n## 仍有疑問的地方\n## 結論",
    },
    {
        "key": "consensus", "name": "共識建構",
        "desc": "雙方目標是找出共同點，逐步縮小分歧、達成可執行的共識。",
        "roles": ("協商者", "協商者"), "blind": True,
        "opening": "請獨立提出你的看法與建議。",
        "debate": ["請先明確列出你與對方已有的共識，再針對分歧提出折衷方案。"],
        "closing": "請提出你能接受的最終共識版本。",
        "synthesis": DEFAULT_SYNTHESIS,
    },
    {
        "key": "teach", "name": "教學問答",
        "desc": "先手當老師講解，後手當學生提問，適合學習新主題。",
        "roles": ("老師（深入淺出講解）", "學生（好奇、會追問、會舉例確認）"), "blind": False, "focus": False,
        "opening": "老師：請用淺顯方式介紹這個主題的核心概念。學生：請針對老師的講解提出不懂的地方或追問。",
        "debate": ["老師：回答學生的問題並舉例。學生：用自己的話複述理解，再提出新的問題。"],
        "closing": "老師：總結重點。學生：說出你學到的三件事。",
        "synthesis": "請整理成學習筆記：\n## 核心概念\n## 常見誤解\n## 例子\n## 延伸學習建議",
    },
    {
        "key": "custom", "name": "自訂角色",
        "desc": "自行設定兩方的角色（例如：律師 vs 會計師、家長 vs 老師）。",
        "roles": ("參與者", "參與者"), "blind": False,
        "opening": "請以你的角色身分，對主題提出觀點與建議。",
        "debate": ["請以你的角色身分，回應對方最新發言並推進討論。"],
        "closing": DEFAULT_CLOSING, "synthesis": DEFAULT_SYNTHESIS,
    },
]
MODE_BY_KEY = {m["key"]: m for m in MODES}


# ---------------------------------------------------------------------------
# 討論場次
# ---------------------------------------------------------------------------

def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_atomic(path, text):
    """先寫暫存檔再置換，避免存檔中途被 Ctrl+C 打斷、留下讀不回來的 state.json。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def list_case_files(folder, limit=200):
    if not folder:
        return []
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d != OUT_DIR_NAME and not d.startswith("."))
        for f in sorted(files):
            if f in IGNORED_FILES or f.startswith("~$"):
                continue
            out.append(os.path.relpath(os.path.join(root, f), folder))
            if len(out) >= limit:
                return out
    return out


class Session:
    def __init__(self, cfg, app):
        self.app = app
        self.lock = threading.RLock()
        self.cfg = cfg                 # topic, mode, rounds, first, synth, roles, length
        self.id = cfg.get("id") or dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.messages = cfg.get("messages", [])
        self.queue = []                # 待執行步驟
        self.status = cfg.get("status", "idle")   # running / paused / idle / done / error
        self.thinking = []
        self.paused = False
        self.stopping = False
        self.round_no = cfg.get("round_no", 0)
        self.worker = None
        self.dir = app.out_dir / self.id

    # ----- 設定 -----
    @property
    def mode(self):
        return MODE_BY_KEY.get(self.cfg.get("mode"), MODES[0])

    def speakers(self):
        first = self.cfg.get("first", "claude")
        return (first, "chatgpt" if first == "claude" else "claude")

    def role_of(self, agent):
        a, _ = self.speakers()
        idx = 0 if agent == a else 1
        custom = (self.cfg.get("roles") or ["", ""])[idx].strip()
        return custom or self.mode["roles"][idx]

    @property
    def focus(self):
        return self.mode.get("focus", True) and self.cfg.get("focus") is not False

    @property
    def issues(self):
        """最近一次的分歧整理（沒有則為 None）"""
        return next((m for m in reversed(self.messages) if m.get("kind") == "issues"), None)

    # ----- 步驟規劃 -----
    def plan_opening(self):
        a, b = self.speakers()
        if self.mode["blind"]:
            steps = [{"phase": "① 各自分析（閉卷）", "agents": [a, b], "task": self.mode["opening"]},
                     {"phase": "② 互相閱讀", "agents": [a, b], "task": self.mode.get("crossread", DEFAULT_CROSSREAD)}]
        else:
            steps = [{"phase": "開場", "agents": [a], "task": self.mode["opening"]},
                     {"phase": "開場", "agents": [b], "task": self.mode["opening"]}]
        if self.focus:
            steps.append(self.issues_step())
        return steps

    def issues_step(self):
        return {"phase": "③ 分歧整理", "agents": [self.cfg.get("synth", "claude")], "task": ISSUES_TASK, "kind": "issues"}

    def plan_rounds(self, n):
        a, b = self.speakers()
        steps = []
        for _ in range(max(0, n)):
            self.round_no += 1
            deb = self.mode["debate"]
            task = deb[min(self.round_no - 1, len(deb) - 1)]
            label = f"第 {self.round_no} 輪"
            order = (a, b) if self.round_no % 2 == 1 or self.cfg.get("alternate") is False else (b, a)
            steps += [{"phase": label, "agents": [order[0]], "task": task, "kind": "round"},
                      {"phase": label, "agents": [order[1]], "task": task, "kind": "round"}]
        return steps

    def plan_closing(self):
        a, b = self.speakers()
        synth = self.cfg.get("synth", "claude")
        return [{"phase": "最終立場", "agents": [a, b], "task": self.mode["closing"], "kind": "closing"},
                {"phase": "結論整合", "agents": [synth], "task": self.mode["synthesis"] + SYNTHESIS_RULES,
                 "synthesis": True}]

    # ----- 主持人操作 -----
    def start(self):
        rounds = int(self.cfg.get("rounds", 2))
        self.add_message("system", f"討論開始｜方式：{self.mode['name']}｜輪數：{rounds}", phase="設定")
        self.queue = self.plan_opening() + self.plan_rounds(rounds) + self.plan_closing()
        self.run_async()

    def host_say(self, text):
        self.add_message("host", text)

    def more_rounds(self, n):
        with self.lock:
            self.queue = [s for s in self.queue if not s.get("synthesis") and s["phase"] != "最終立場"]
            self.queue += self.plan_rounds(n) + self.plan_closing()
        self.add_message("system", f"主持人要求再討論 {n} 輪", phase="主持")
        self.run_async()

    def conclude(self):
        with self.lock:
            self.queue = self.plan_closing()
        self.add_message("system", "主持人要求進入結論", phase="主持")
        self.run_async()

    def ask_one(self, agent):
        with self.lock:
            self.queue.insert(0, {"phase": "主持人點名", "agents": [agent], "kind": "round",
                                  "task": "主持人點名請你發言：請直接回應主持人最新的插話或問題。"})
        self.run_async()

    def reissue(self):
        """重新整理分歧（例如主持人補充了新條件之後）"""
        with self.lock:
            self.queue.insert(0, self.issues_step())
        self.add_message("system", "主持人要求重新整理分歧", phase="主持")
        self.run_async()

    def pause(self, on):
        self.paused = on
        with self.lock:
            if self.status in ("running", "paused"):
                self.status = "paused" if on else "running"
        self.save()

    def stop(self):
        with self.lock:
            self.queue = []
        self.paused = False
        self.add_message("system", "主持人結束討論（可再提問並按「繼續討論」）", phase="主持")

    # ----- 執行 -----
    def run_async(self):
        self.paused = False
        with self.lock:
            if self.worker and self.worker.is_alive():
                return
            self.status = "running"
            self.worker = threading.Thread(target=self._loop, daemon=True)
            self.worker.start()

    def _loop(self):
        try:
            while True:
                while self.paused:
                    time.sleep(0.3)
                with self.lock:
                    if not self.queue:
                        break
                    step = self.queue.pop(0)
                self._run_step(step)
            with self.lock:
                self.status = "done" if any(m.get("synthesis") for m in self.messages) else "idle"
        except Exception as e:  # noqa: BLE001
            self.add_message("system", f"錯誤：{e}", phase="錯誤")
            with self.lock:
                self.queue = []          # 別讓剩下的步驟繼續跑下去
                self.status = "error"
        finally:
            self.thinking = []
            self.save()

    def _run_step(self, step):
        snapshot = list(self.messages)  # 同一步驟的兩方共用快照 → 閉卷時彼此看不到
        agents = step["agents"]
        self.thinking = list(agents)
        results = {}

        def work(agent):
            prompt = self.build_prompt(agent, step, snapshot)
            try:
                results[agent] = (ask(agent, prompt, self.app.case_dir or str(self.dir), self.app.mock), None)
            except Exception as e:  # noqa: BLE001
                results[agent] = (None, str(e))

        threads = [threading.Thread(target=work, args=(ag,)) for ag in agents]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        spoke = 0
        for ag in agents:
            text, err = results[ag]
            if err:
                self.add_message("system", f"{AGENTS[ag]['name']} 發生錯誤：{err}", phase="錯誤")
            else:
                spoke += 1
                self.add_message(ag, text, phase=step["phase"], synthesis=step.get("synthesis", False),
                                 kind=step.get("kind", ""))
        self.thinking = []
        if not spoke:
            # 這一步沒有任何人成功發言，後面的步驟只會重複失敗並繼續消耗額度。
            raise RuntimeError("這一步沒有任何一方成功發言，已停止排程以免繼續消耗額度。"
                               "請處理上面的錯誤訊息，再按「再討論」接續。")

    # ----- 提示詞 -----
    def build_prompt(self, agent, step, messages):
        other = "chatgpt" if agent == "claude" else "claude"
        me, you = AGENTS[agent]["name"], AGENTS[other]["name"]
        mode = self.mode
        parts = [
            f"你是 {me}，正在參與一場由人類主持人主持的雙 AI 討論，另一位參與者是 {you}。",
            f"討論方式：{mode['name']} —— {mode['desc']}",
            f"你的角色：{self.role_of(agent)}；{you} 的角色：{self.role_of(other)}。",
            f"\n【討論主題】\n{self.cfg.get('topic', '').strip()}",
        ]
        if self.app.case_dir:
            files = list_case_files(self.app.case_dir)
            parts.append("\n【案件資料】目前工作目錄就是案件資料夾（唯讀，請勿修改或新增任何檔案），"
                         "需要時請自行開檔閱讀並註明出處。檔案清單：\n" + "\n".join(f"- {f}" for f in files))

        history = self.format_transcript(messages)
        if history:
            parts.append("\n【到目前為止的討論紀錄】\n" + history)

        last_mine = max((i for i, m in enumerate(messages) if m["speaker"] == agent), default=-1)
        new_host = [m["text"] for m in messages[last_mine + 1:] if m["speaker"] == "host"]
        if new_host and not step.get("synthesis"):
            parts.append("\n【主持人最新插話（請優先回應）】\n" + "\n".join(f"- {t}" for t in new_host))

        issues = self.issues
        if issues and step.get("kind") in ("round", "closing"):
            by = AGENTS[issues["speaker"]]["name"]
            parts.append(f"\n【本場聚焦的分歧（由 {by} 以中立書記身分整理）】\n{issues['text']}\n{FOCUS_RULE}")

        length = self.cfg.get("length", "約 300～500 字")
        parts.append(f"\n【本輪任務】\n{step['task']}")
        parts.append(f"\n發言規則：使用繁體中文；直接寫出你的發言內容（不要加「{me}：」前綴）；"
                     f"長度{length}；可以同意對方，但不要為了客氣而附和，有不同意見要直說並給理由。")
        return "\n".join(parts)

    @staticmethod
    def format_transcript(messages):
        lines = []
        for m in messages:
            if m["speaker"] == "system":
                continue
            who = "主持人" if m["speaker"] == "host" else AGENTS[m["speaker"]]["name"]
            lines.append(f"[{who}]（{m.get('phase', '')}）\n{m['text']}\n" if m["speaker"] != "host"
                         else f"[主持人] {m['text']}\n")
        text = "\n".join(lines)
        if len(text) > MAX_TRANSCRIPT_CHARS:
            head = text[:4000]
            tail = text[-(MAX_TRANSCRIPT_CHARS - 4000):]
            text = head + "\n……（中間紀錄過長已省略，完整內容見 transcript.md）……\n" + tail
        return text

    # ----- 紀錄 -----
    def add_message(self, speaker, text, phase="", synthesis=False, kind=""):
        with self.lock:
            self.messages.append({"speaker": speaker, "text": text, "phase": phase,
                                  "time": now(), "synthesis": synthesis, "kind": kind})
        self.save()

    def to_dict(self):
        return {**{k: v for k, v in self.cfg.items() if k != "messages"},
                "id": self.id, "status": self.status, "round_no": self.round_no,
                "case_dir": self.app.case_dir, "messages": self.messages}

    def save(self):
        with self.lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            data = self.to_dict()
            write_atomic(self.dir / "state.json", json.dumps(data, ensure_ascii=False, indent=2))
            write_atomic(self.dir / "transcript.md", self.to_markdown())

    def to_markdown(self):
        md = [f"# 雙 AI 討論紀錄：{self.cfg.get('topic', '').strip()[:60]}", "",
              f"- 討論方式：{self.mode['name']}",
              f"- 角色：Claude＝{self.role_of('claude')}；ChatGPT＝{self.role_of('chatgpt')}",
              f"- 案件資料夾：{self.app.case_dir or '（無）'}", f"- 場次編號：{self.id}", "",
              "## 主題", "", self.cfg.get("topic", ""), ""]
        for m in self.messages:
            who = {"host": "🧑 主持人", "system": "⚙️ 系統"}.get(m["speaker"], AGENTS.get(m["speaker"], {}).get("name", m["speaker"]))
            md += [f"### {who}｜{m.get('phase', '')}｜{m['time']}", "", m["text"], ""]
        return "\n".join(md)

    def view(self, since=0):
        with self.lock:
            return {"id": self.id, "status": self.status, "thinking": self.thinking,
                    "paused": self.paused, "queue": len(self.queue), "total": len(self.messages),
                    "messages": self.messages[since:], "mode": self.mode["name"],
                    "topic": self.cfg.get("topic", ""), "round_no": self.round_no,
                    "roles": {"claude": self.role_of("claude"), "chatgpt": self.role_of("chatgpt")}}


class App:
    def __init__(self, case_dir, mock):
        self.case_dir = str(Path(case_dir).resolve()) if case_dir else ""
        self.mock = mock
        base = Path(self.case_dir) if self.case_dir else Path.cwd()
        self.out_dir = base / OUT_DIR_NAME
        self.sessions = {}

    def history(self):
        items = []
        if self.out_dir.exists():
            for p in sorted(self.out_dir.glob("*/state.json"), reverse=True):
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    items.append({"id": d["id"], "topic": d.get("topic", "")[:60],
                                  "mode": MODE_BY_KEY.get(d.get("mode"), MODES[0])["name"],
                                  "count": len(d.get("messages", []))})
                except (OSError, ValueError, KeyError):
                    continue
        return items

    def get(self, sid):
        if sid in self.sessions:
            return self.sessions[sid]
        p = self.out_dir / sid / "state.json"
        if not re.fullmatch(r"[\w-]+", sid) or not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("status") in ("running", "paused"):
            d["status"] = "idle"
        s = Session(d, self)
        self.sessions[sid] = s
        return s


# ---------------------------------------------------------------------------
# HTTP 伺服器（只綁 127.0.0.1）
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    app: App = None

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        if url.path == "/":
            return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if url.path == "/api/info":
            return self._send(200, {
                "case_dir": self.app.case_dir, "out_dir": str(self.app.out_dir), "mock": self.app.mock,
                "files": list_case_files(self.app.case_dir, 50),
                "modes": [{**{k: m[k] for k in ("key", "name", "desc", "roles", "blind")}, "focus": m.get("focus", True)} for m in MODES],
                "cli": {"claude": bool(shutil.which("claude")), "codex": bool(shutil.which("codex"))},
                "history": self.app.history()})
        if len(parts) == 3 and parts[:2] == ["api", "session"]:
            s = self.app.get(parts[2])
            if not s:
                return self._send(404, {"error": "找不到場次"})
            q = dict(p.split("=", 1) for p in url.query.split("&") if "=" in p)
            return self._send(200, s.view(int(q.get("since", 0) or 0)))
        if len(parts) == 4 and parts[:2] == ["api", "session"] and parts[3] == "transcript.md":
            s = self.app.get(parts[2])
            if not s:
                return self._send(404, {"error": "找不到場次"})
            return self._send(200, s.to_markdown().encode("utf-8"), "text/markdown; charset=utf-8")
        self._send(404, {"error": "not found"})

    def do_POST(self):
        # 僅接受同源請求，避免其他網頁從瀏覽器對本機主持台下指令
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return self._send(403, {"error": "forbidden"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, {"error": "bad json"})
        parts = [p for p in urlparse(self.path).path.split("/") if p]

        if parts == ["api", "start"]:
            if not str(body.get("topic", "")).strip():
                return self._send(400, {"error": "請輸入討論題目"})
            cfg = {k: body.get(k) for k in ("topic", "mode", "rounds", "first", "synth", "roles", "length", "alternate", "focus")}
            cfg["created"] = now()
            s = Session(cfg, self.app)
            self.app.sessions[s.id] = s
            s.start()
            return self._send(200, {"id": s.id})

        if len(parts) == 4 and parts[:2] == ["api", "session"]:
            s = self.app.get(parts[2])
            if not s:
                return self._send(404, {"error": "找不到場次"})
            action = parts[3]
            if action == "say":
                text = str(body.get("text", "")).strip()
                if text:
                    s.host_say(text)
                if body.get("continue"):
                    if body.get("target") in AGENTS:
                        s.ask_one(body["target"])
                    elif s.status not in ("running", "paused"):
                        s.more_rounds(int(body.get("rounds", 1)))
            elif action == "more":
                s.more_rounds(int(body.get("rounds", 1)))
            elif action == "reissue":
                s.reissue()
            elif action == "conclude":
                s.conclude()
            elif action == "pause":
                s.pause(bool(body.get("on", True)))
            elif action == "stop":
                s.stop()
            else:
                return self._send(404, {"error": "unknown action"})
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})


PAGE = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>雙 AI 會診台</title>
<style>
:root{--bg:#f6f4ef;--card:#fff;--ink:#222;--muted:#777;--line:#e2ddd3;--claude:#c96a2b;--claude-bg:#fbeee3;
--gpt:#2f6fb5;--gpt-bg:#e8f0fa;--host:#3b3b3b;--host-bg:#efefef;--accent:#1f1f1f}
@media (prefers-color-scheme: dark){:root{--bg:#1b1a18;--card:#262522;--ink:#eee;--muted:#9a968e;--line:#3a3833;
--claude-bg:#3a2a1e;--gpt-bg:#1d2a3a;--host-bg:#2f2f2f;--host:#ddd;--accent:#eee}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 -apple-system,"Noto Sans TC","Microsoft JhengHei",sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header h1{font-size:18px;margin:0}.pill{font-size:12px;padding:2px 10px;border-radius:99px;background:var(--host-bg);color:var(--muted)}
main{max-width:980px;margin:0 auto;padding:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:14px}
label{display:block;font-weight:600;margin:10px 0 4px}textarea,input,select{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit}
textarea{min-height:90px;resize:vertical}.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.modes{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px}
.mode{border:1px solid var(--line);border-radius:10px;padding:10px;cursor:pointer;background:var(--bg)}
.mode.sel{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}.mode b{display:block}.mode small{color:var(--muted)}
button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
button.primary{background:var(--accent);color:var(--bg);border-color:var(--accent)}button:disabled{opacity:.45;cursor:default}
.hint{color:var(--muted);font-size:13px}.warn{color:#b3261e}
#chat{display:flex;flex-direction:column;gap:12px;padding-bottom:180px}
.msg{max-width:88%;padding:10px 14px;border-radius:12px;white-space:pre-wrap;word-break:break-word}
.msg .who{font-size:12px;font-weight:700;margin-bottom:4px}
.msg.claude{background:var(--claude-bg);border-left:4px solid var(--claude);align-self:flex-start}.msg.claude .who{color:var(--claude)}
.msg.chatgpt{background:var(--gpt-bg);border-right:4px solid var(--gpt);align-self:flex-end}.msg.chatgpt .who{color:var(--gpt)}
.msg.host{background:var(--host-bg);align-self:center;border:1px dashed var(--muted);max-width:75%}
.msg.system{align-self:center;background:none;color:var(--muted);font-size:13px;padding:2px}
.msg.synthesis{max-width:100%;align-self:stretch;border:2px solid var(--accent)}
.msg.issues{max-width:100%;align-self:stretch;border:2px dashed var(--accent);background:var(--card)}
.msg .tag{display:inline-block;font-size:11px;padding:0 8px;margin-right:6px;border-radius:99px;background:var(--accent);color:var(--bg)}
.check{display:flex;gap:8px;align-items:center;font-weight:400;margin-top:14px}.check input{width:auto}
.thinking{color:var(--muted);font-size:14px;align-self:center}.dots::after{content:"…";animation:d 1.2s infinite}
@keyframes d{0%{content:"."}33%{content:".."}66%{content:"..."}}
#bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:10px 16px}
#bar .inner{max-width:980px;margin:0 auto}#bar .btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;align-items:center}
#bar textarea{min-height:52px}.hidden{display:none!important}
.hist a{display:block;padding:6px 0;color:var(--ink);text-decoration:none;border-bottom:1px solid var(--line)}
</style>
</head>
<body>
<header><h1>🩺 雙 AI 會診台</h1><span class="pill">Claude × ChatGPT</span><span id="casePill" class="pill"></span><span id="statusPill" class="pill"></span></header>
<main>
<section id="setup">
  <div class="card">
    <div id="cliWarn" class="warn hint"></div>
    <label>討論題目 / 要它們處理的問題</label>
    <textarea id="topic" placeholder="例：這份租賃契約對承租人有哪些風險？下一步應該怎麼處理？"></textarea>
    <div id="files" class="hint"></div>
    <label>討論方式</label>
    <div id="modes" class="modes"></div>
    <div id="rolesBox" class="row">
      <div><label>先手角色（選填）</label><input id="roleA" placeholder=""></div>
      <div><label>後手角色（選填）</label><input id="roleB" placeholder=""></div>
    </div>
    <div class="row">
      <div><label>先發言</label><select id="first"><option value="claude">Claude</option><option value="chatgpt">ChatGPT</option></select></div>
      <div><label>討論輪數</label><select id="rounds"><option>1</option><option selected>2</option><option>3</option><option>4</option><option>6</option></select></div>
      <div><label>結論由誰整合</label><select id="synth"><option value="claude">Claude</option><option value="chatgpt">ChatGPT</option></select></div>
      <div><label>每次發言長度</label><select id="length"><option>約 150～300 字</option><option selected>約 300～500 字</option><option>約 600～1000 字，可以詳細</option></select></div>
    </div>
    <label class="check" id="focusBox"><input type="checkbox" id="focus" checked> 聚焦分歧：開場後先整理出最多 3 個主要分歧，之後每輪只討論這些</label>
    <p style="margin-top:16px"><button class="primary" id="startBtn">開始討論</button></p>
  </div>
  <div class="card hist"><b>繼續上次議程</b><div id="history" class="hint">（尚無紀錄）</div></div>
</section>

<section id="room" class="hidden">
  <div class="card"><b id="roomTopic"></b><div class="hint" id="roomMeta"></div></div>
  <div id="chat"></div>
</section>
</main>

<div id="bar" class="hidden"><div class="inner">
  <textarea id="say" placeholder="主持人插話：提出問題、補充資訊、指定方向…（Ctrl+Enter 送出）"></textarea>
  <div class="btns">
    <button class="primary" id="sendBtn">送出插話</button>
    <select id="target" style="width:auto"><option value="">由下一位回應</option><option value="claude">點名 Claude 回答</option><option value="chatgpt">點名 ChatGPT 回答</option></select>
    <button id="pauseBtn">⏸ 暫停</button>
    <button id="moreBtn">➕ 再討論</button><select id="moreN" style="width:auto"><option>1</option><option selected>2</option><option>3</option></select><span class="hint">輪</span>
    <button id="reissueBtn" title="補充新條件後，請它們重新判斷分歧">🧭 重新整理分歧</button>
    <button id="concludeBtn">🏁 請下結論</button>
    <button id="stopBtn">⏹ 結束</button>
    <a id="dl" class="hint" target="_blank">下載紀錄</a>
    <button id="newBtn">新議題</button>
  </div>
</div></div>

<script>
const $=s=>document.querySelector(s);let info,mode,sid=null,since=0,timer=null,state={};
const NAMES={claude:"Claude",chatgpt:"ChatGPT",host:"🧑 主持人",system:""};
async function api(p,b){const r=await fetch(p,b?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)}:{});const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
function esc(s){return s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}
async function init(){
  info=await api("/api/info");
  $("#casePill").textContent=info.case_dir?("📁 "+info.case_dir):"未指定案件資料夾";
  if(info.mock)$("#statusPill").textContent="模擬模式";
  const miss=[];if(!info.cli.claude)miss.push("claude");if(!info.cli.codex)miss.push("codex");
  if(miss.length&&!info.mock)$("#cliWarn").textContent="⚠ 找不到指令："+miss.join("、")+"。請先安裝並登入（見 SKILL.md），或用 --mock 試跑。";
  if(info.files.length)$("#files").textContent="案件檔案（"+info.files.length+"）："+info.files.slice(0,12).join("、")+(info.files.length>12?"…":"");
  $("#modes").innerHTML=info.modes.map(m=>`<div class="mode" data-k="${m.key}"><b>${m.name}${m.blind?" 🙈":""}</b><small>${m.desc}</small></div>`).join("");
  document.querySelectorAll(".mode").forEach(el=>el.onclick=()=>pick(el.dataset.k));
  pick(info.case_dir?"consult":"free");
  $("#history").innerHTML=info.history.length?info.history.map(h=>`<a href="#${h.id}">${esc(h.topic||"(無題)")} <span class="hint">｜${h.mode}｜${h.count} 則</span></a>`).join(""):"（尚無紀錄）";
  if(location.hash.length>1)openRoom(location.hash.slice(1));
}
function pick(k){mode=info.modes.find(m=>m.key===k);document.querySelectorAll(".mode").forEach(e=>e.classList.toggle("sel",e.dataset.k===k));
  $("#roleA").placeholder=mode.roles[0];$("#roleB").placeholder=mode.roles[1];
  $("#focus").disabled=!mode.focus;$("#focusBox").style.opacity=mode.focus?1:.45;}
window.onhashchange=()=>{const h=location.hash.slice(1);if(h&&h!==sid)openRoom(h)};
$("#startBtn").onclick=async()=>{
  try{const r=await api("/api/start",{topic:$("#topic").value,mode:mode.key,rounds:+$("#rounds").value,first:$("#first").value,
    synth:$("#synth").value,length:$("#length").value,roles:[$("#roleA").value,$("#roleB").value],focus:mode.focus&&$("#focus").checked});location.hash=r.id;}catch(e){alert(e.message)}};
function openRoom(id){sid=id;since=0;$("#chat").innerHTML="";$("#setup").classList.add("hidden");$("#room").classList.remove("hidden");$("#bar").classList.remove("hidden");
  $("#dl").href=`/api/session/${id}/transcript.md`;clearInterval(timer);poll();timer=setInterval(poll,1200);}
async function poll(){
  let v;try{v=await api(`/api/session/${sid}?since=${since}`)}catch(e){return}
  state=v;$("#roomTopic").textContent=v.topic;$("#roomMeta").textContent=`${v.mode}｜Claude＝${v.roles.claude}｜ChatGPT＝${v.roles.chatgpt}`;
  const nearBottom=innerHeight+scrollY>=document.body.scrollHeight-260;
  document.querySelector(".thinking")?.remove();
  for(const m of v.messages){const d=document.createElement("div");d.className="msg "+m.speaker+(m.synthesis?" synthesis":"")+(m.kind==="issues"?" issues":"");
    const tag=m.kind==="issues"?'<span class="tag">🧭 分歧整理</span>':m.synthesis?'<span class="tag">🏁 結論</span>':"";
    const who=m.speaker==="system"?"":`<div class="who">${tag}${NAMES[m.speaker]}${m.phase?"｜"+esc(m.phase):""}<span class="hint"> ${m.time.slice(11,16)}</span></div>`;
    d.innerHTML=who+esc(m.text);$("#chat").appendChild(d);}
  since=v.total;
  if(v.thinking.length){const t=document.createElement("div");t.className="thinking";t.innerHTML=v.thinking.map(a=>NAMES[a]).join(" 與 ")+" 思考中<span class=dots></span>";$("#chat").appendChild(t);}
  const map={running:"🟢 討論中",paused:"⏸ 已暫停（目前發言完才停）",idle:"⚪ 待命：可插話後按「再討論」",done:"✅ 已完成：可再提問繼續",error:"🔴 發生錯誤"};
  $("#statusPill").textContent=(info.mock?"模擬｜":"")+(map[v.status]||v.status);
  $("#pauseBtn").textContent=v.paused?"▶ 繼續":"⏸ 暫停";const busy=v.status==="running"||v.status==="paused";
  $("#pauseBtn").disabled=!busy;$("#stopBtn").disabled=!busy;
  $("#sendBtn").textContent=busy?"送出插話":"送出並繼續討論";
  if(nearBottom&&v.messages.length)scrollTo(0,document.body.scrollHeight);
}
async function act(a,b={}){try{await api(`/api/session/${sid}/${a}`,b);poll()}catch(e){alert(e.message)}}
$("#sendBtn").onclick=()=>{const text=$("#say").value.trim(),target=$("#target").value;if(!text&&!target)return;
  act("say",{text,target,continue:true,rounds:+$("#moreN").value});$("#say").value="";};
$("#say").onkeydown=e=>{if(e.key==="Enter"&&(e.ctrlKey||e.metaKey))$("#sendBtn").click()};
$("#pauseBtn").onclick=()=>act("pause",{on:!state.paused});
$("#moreBtn").onclick=()=>act("more",{rounds:+$("#moreN").value});
$("#concludeBtn").onclick=()=>act("conclude");
$("#reissueBtn").onclick=()=>act("reissue");
$("#stopBtn").onclick=()=>{if(confirm("結束目前排程？（已完成的發言都會保留）"))act("stop")};
$("#newBtn").onclick=()=>{clearInterval(timer);sid=null;history.pushState("",document.title,location.pathname);location.reload()};
init();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 連線自我檢查（--check）
# ---------------------------------------------------------------------------

CHECK_TIMEOUT = int(os.environ.get("DEBATE_CHECK_TIMEOUT", "180"))
CHECK_PROMPT = "這是連線測試。請只回覆四個字：連線正常"
CHECK_TARGETS = [("claude", "claude", "Claude Code", "claude"),
                 ("chatgpt", "codex", "ChatGPT Codex CLI", "codex login")]


def check_clis(workdir):
    """用最短的提示詞各問一次，確認兩個 CLI 真的裝好、登入好、會回話。

    比直接開一場討論便宜得多：每邊只花一次極短的回覆，出問題也馬上看到原因。
    """
    print(f"檢查兩個 CLI（每邊最多等 {CHECK_TIMEOUT} 秒）…")
    bad = []
    for agent, exe, label, login_hint in CHECK_TARGETS:
        print(f"\n── {label}（{exe}）")
        # 不在這裡先 which()：實際用的指令可能被 DEBATE_*_CMD 換成完整路徑，
        # 那樣 which("claude") 會找不到卻其實可用。交給 run_cli 解析並回報。
        t0 = time.time()
        try:
            text = ask(agent, CHECK_PROMPT, workdir, False, timeout=CHECK_TIMEOUT)
        except Exception as e:  # noqa: BLE001
            print(f"   ✗ 呼叫失敗（{time.time() - t0:.0f} 秒）：")
            print("     " + str(e).replace("\n", "\n     "))
            print(f"   → 若是登入問題，請執行 `{login_hint}`。")
            bad.append(label)
            continue
        print(f"   ✓ 有回覆（{time.time() - t0:.0f} 秒）：{' '.join(text.split())[:80]}")

    if bad:
        print("\n有問題的是：" + "、".join(bad) + "。處理完再跑一次 --check。")
        return False
    print("\n兩邊都正常，可以開始討論了。")
    return True


def main():
    ap = argparse.ArgumentParser(description="雙 AI 會診 / 討論主持台")
    ap.add_argument("case_dir", nargs="?", default="", help="案件資料夾（選填）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("DEBATE_PORT", "8765")))
    ap.add_argument("--mock", action="store_true", help="模擬模式：不呼叫真的 AI")
    ap.add_argument("--check", action="store_true",
                    help="只檢查兩個 CLI 是否裝好、登入好、會回話（各花一次極短回覆）")
    ap.add_argument("--no-browser", action="store_true", help="不要自動開瀏覽器")
    args = ap.parse_args()

    if args.case_dir and not os.path.isdir(args.case_dir):
        sys.exit(f"找不到資料夾：{args.case_dir}")
    if args.check:
        sys.exit(0 if check_clis(args.case_dir or os.getcwd()) else 1)
    if not args.mock:
        for c in ("claude", "codex"):
            if not shutil.which(c):
                print(f"⚠ 找不到 {c} 指令，請先安裝並登入（或加 --mock 試跑）。")

    Handler.app = App(args.case_dir, args.mock)
    port = args.port
    for _ in range(20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    else:
        sys.exit("找不到可用的連接埠")
    url = f"http://127.0.0.1:{port}/"
    print(f"雙 AI 會診台已啟動：{url}")
    print(f"產出資料夾：{Handler.app.out_dir}")
    print("按 Ctrl+C 結束。")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已結束。")


if __name__ == "__main__":
    main()
