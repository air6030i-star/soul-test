#!/usr/bin/env bash
# Life OS 資料夾體檢
# 用法：bash lifeos/scripts/folder-health.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
TODO=lifeos/100_Todo/projects
INBOX=lifeos/100_Todo/inbox

echo "資料夾體檢 $(date +%F)"
echo

echo "── 1. 隱私（最優先）──"
LEAK=$(git ls-files lifeos/100_Todo lifeos/300_Journal lifeos/900_Archive lifeos/200_Reference/private 2>/dev/null \
       | grep -v '\.gitkeep$' | grep -v 'private/README.md$')
if [ -n "$LEAK" ]; then
  echo "  !! 外洩風險：以下檔案已被 git 追蹤（這個 repo 是 public）"
  echo "$LEAK" | sed 's/^/     /'
  echo "     處理：git rm --cached <檔案>，並確認 .gitignore"
else
  echo "  通過：資料層沒有檔案進 git"
fi
echo

echo "── 2. 命名規則 ──"
BAD=0
if [ -d "$TODO" ]; then
  for f in "$TODO"/*.md; do
    [ -e "$f" ] || continue
    b=$(basename "$f")
    case "$b" in
      *" "*)            echo "  [空白] $b"; BAD=1 ;;
    esac
    echo "$b" | grep -qE '最新|final|FINAL|v[0-9]+-?(最後|真的)' && { echo "  [狀態字] $b"; BAD=1; }
    echo "$b" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}-' || { echo "  [日期格式] $b 應為 YYYY-MM-DD-主題.md"; BAD=1; }
    echo "$b" | grep -qE '：|？|！|（|）' && { echo "  [全形標點] $b"; BAD=1; }
  done
fi
[ "$BAD" -eq 0 ] && echo "  通過"
echo

echo "── 3. Frontmatter 完整性 ──"
MISS=0
if [ -d "$TODO" ]; then
  for f in "$TODO"/*.md; do
    [ -e "$f" ] || continue
    for k in 路線 狀態 對象 截止 預估工時 實際工時; do
      grep -q "^${k}:" "$f" || { echo "  [缺 $k] $(basename "$f")"; MISS=1; }
    done
    st=$(grep -m1 '^狀態:' "$f" | sed 's/^狀態: *//')
    case "$st" in 待開始|進行中|等對方|完成|取消|"") ;; *) echo "  [狀態值非法] $(basename "$f") = $st"; MISS=1 ;; esac
  done
fi
[ "$MISS" -eq 0 ] && echo "  通過"
echo

echo "── 4. 該封存沒封存 ──"
N=0
if [ -d "$TODO" ]; then
  for f in "$TODO"/*.md; do
    [ -e "$f" ] || continue
    grep -qE '^狀態: *(完成|取消)' "$f" && { echo "  $(basename "$f")"; N=1; }
  done
fi
[ "$N" -eq 0 ] && echo "  通過" || echo "  → 走 memory-writeback 封存到 lifeos/900_Archive/"
echo

echo "── 5. 卡住的案子 ──"
N=0
if [ -d "$TODO" ]; then
  for f in "$TODO"/*.md; do
    [ -e "$f" ] || continue
    days=$(( ( $(date +%s) - $(date -r "$f" +%s) ) / 86400 ))
    if grep -q '^狀態: *等對方' "$f" && [ "$days" -gt 7 ]; then
      echo "  [等對方 ${days} 天] $(basename "$f") → 追 / 再等 / 放掉？"; N=1
    elif grep -q '^狀態: *進行中' "$f" && [ "$days" -gt 14 ]; then
      echo "  [停滯 ${days} 天] $(basename "$f")"; N=1
    fi
  done
fi
[ "$N" -eq 0 ] && echo "  通過"
echo

echo "── 6. Inbox 積壓 ──"
C=$(ls -1 "$INBOX" 2>/dev/null | grep -v '^\.gitkeep$' | wc -l | tr -d ' ')
echo "  待分流：$C 件"
[ "$C" -gt 5 ] && echo "  → 超過 5 件，建議排一次集中分流（task-intake）"
