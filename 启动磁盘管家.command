#!/bin/zsh
cd -- "$(dirname "$0")" || exit 1
if [[ -x /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 ]]; then
  exec /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 launcher.py
elif command -v python3 >/dev/null 2>&1; then
  exec python3 launcher.py
else
  print "需要 Python 3.10 或更新版本。这是本机网页测试版，正式 App 将另行打包。"
  read
fi
