#!/usr/bin/env bash
# Soul Universe 網站健檢：meta / 定價 / 內部連結 / 中文編碼 / 頁數
# 用法：bash lifeos/scripts/health-check.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1

PAGES=$(ls *.html 2>/dev/null; ls */*.html 2>/dev/null | grep -v '^lifeos/')
echo "網站健檢 $(date +%F)"
echo "檢查頁面：$(echo "$PAGES" | wc -l) 個"
echo

echo "── 1. Meta 覆蓋 ──"
printf "%-28s %-6s %-6s %-5s %-10s\n" 檔案 title desc og canonical
for f in $PAGES; do
  printf "%-28s %-6s %-6s %-5s %-10s\n" "$f" \
    "$(grep -ac '<title>' "$f")" \
    "$(grep -ac 'name="description"' "$f")" \
    "$(grep -ac 'property="og:' "$f")" \
    "$(grep -ac 'rel="canonical"' "$f")"
done
echo

echo "── 2. 定價一致性 ──"
grep -aohE 'NT\$ ?[0-9,]+|US\$ ?[0-9,]+' $PAGES | sort | uniq -c | sort -rn
echo
echo "（同一產品若在不同頁出現不同金額，或出現已下架舊價，就要修。改價務必全站一次改完。）"
echo

echo "── 3. 內部連結 ──"
# 站內連結有兩種寫法：相對路徑，以及指向 Pages 網域的絕對網址
SELF_ORIGIN="https://air6030i-star.github.io/soul-test"
BROKEN=0
for f in $PAGES; do
  dir=$(dirname "$f")
  for link in $(grep -aohE 'href="[^"]+\.html[^"]*"' "$f" \
                | sed 's/href="//; s/"$//' \
                | sed "s#^${SELF_ORIGIN}/##" \
                | sed -E 's/[#?].*$//' \
                | grep -vE '^(https?|mailto):' | sort -u); do
    [ -z "$link" ] && continue
    case "$link" in /*) target=".${link}" ;; *) target="$dir/$link" ;; esac
    if [ ! -f "$target" ]; then echo "  [壞連結] $f -> $link"; BROKEN=1; fi
  done
done
[ "$BROKEN" -eq 0 ] && echo "  通過：站內連結都指得到"
echo

echo "── 4. NUL byte / 檔案完整性 ──"
NULBAD=0
for f in $PAGES; do
  n=$(tr -dc '\000' < "$f" | wc -c | tr -d ' ')
  if [ "$n" -gt 0 ]; then
    echo "  !! $f 含 $n 個 NUL byte（git 會當成二進位檔，diff 失效）"
    echo "     修法：python3 -c \"import sys;p='$f';d=open(p,'rb').read().replace(b'\\x00',b'');open(p,'wb').write(d)\""
    NULBAD=1
  fi
done
[ "$NULBAD" -eq 0 ] && echo "  通過"
echo

echo "── 5. 中文編碼（雙重 UTF-8 亂碼）──"
if grep -al 'ä¸\|æ\x9c\|ç\x9a\|ï¼\x88\|å\x8f' $PAGES 2>/dev/null; then
  echo "  !! 上列檔案疑似亂碼"
else
  echo "  通過，沒有偵測到典型亂碼字串"
fi
echo

echo "── 6. 頁數描述一致性 ──"
grep -aohE '[0-9]+ ?頁' $PAGES | sort | uniq -c | sort -rn
echo
echo "── 其他 ──"
[ -f robots.txt ] && echo "  robots.txt：有" || echo "  robots.txt：無（既有缺口）"
[ -f sitemap.xml ] && echo "  sitemap.xml：有" || echo "  sitemap.xml：無（既有缺口）"
