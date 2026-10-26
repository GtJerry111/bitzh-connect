#!/bin/bash
APP="/Applications/BITZH Connect.app"

if [ ! -d "$APP" ]; then
  osascript -e 'display dialog "请先把 BITZH Connect 拖到 Applications 文件夹，然后再运行本脚本。" buttons {"好"} with icon caution'
  exit 1
fi

if ! /usr/bin/xattr -rd com.apple.quarantine "$APP" 2>/dev/null; then
  osascript -e "do shell script \"/usr/bin/xattr -rd com.apple.quarantine \" & quoted form of \"$APP\" with administrator privileges"
fi

open "$APP"
