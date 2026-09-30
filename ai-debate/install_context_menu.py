"""Windows：在資料夾右鍵選單加入「雙 AI 會診」。執行一次即可；加 --remove 移除。（寫入 HKCU，不需管理員）"""
import sys
import winreg
from pathlib import Path

KEYS = [r"Software\Classes\Directory\shell\AIDebate", r"Software\Classes\Directory\Background\shell\AIDebate"]
script = Path(__file__).with_name("debate.py").resolve()
python = Path(sys.executable).with_name("python.exe")

for i, key in enumerate(KEYS):
    if "--remove" in sys.argv:
        for sub in (key + r"\command", key):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except FileNotFoundError:
                pass
        continue
    arg = "%1" if i == 0 else "%V"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        winreg.SetValue(k, "", winreg.REG_SZ, "雙 AI 會診")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
        winreg.SetValue(k, "", winreg.REG_SZ, f'"{python}" "{script}" "{arg}"')
print("已移除" if "--remove" in sys.argv else "已加入右鍵選單：在資料夾（或資料夾空白處）按右鍵 →「雙 AI 會診」")
