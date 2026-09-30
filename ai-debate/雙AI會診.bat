@echo off
chcp 65001 >nul
rem 用法：把案件資料夾拖到這個檔案上，或直接雙擊（不指定資料夾）
python "%~dp0debate.py" %*
pause
