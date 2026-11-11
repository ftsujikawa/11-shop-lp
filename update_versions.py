#!/usr/bin/env python3
"""index.html が読み込む CSS / JS / アイコンの URL に、中身から作ったバージョンを付ける。

  style.css  →  style.css?v=1a2b3c4d

ファイルの中身が変わるとバージョンも変わるので、キャッシュを長くしても
再訪問したユーザーに古いファイルが出続けることはない。
style.css / script.js / img/ を編集したら、公開前に必ず実行する。

  python3 update_versions.py           # index.html を更新
  python3 update_versions.py --check   # 更新が必要かだけ確認（必要なら終了コード 1）
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "index.html"
ASSETS = ["style.css", "script.min.js", "img/favicon.svg"]


def version_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="書き換えずに確認だけする")
    args = ap.parse_args()

    html = HTML.read_text(encoding="utf-8")
    updated = html
    for name in ASSETS:
        v = version_of(ROOT / name)
        pattern = re.compile(r'((?:href|src)=")' + re.escape(name) + r'(?:\?v=[0-9a-f]*)?(")')
        updated, count = pattern.subn(rf"\g<1>{name}?v={v}\g<2>", updated)
        print(f"{name:<16} v={v}  （index.html 内 {count} か所）")
        if count == 0:
            print(f"  ※ index.html に {name} の参照が見つかりません", file=sys.stderr)

    if updated == html:
        print("index.html は最新です。")
        return 0
    if args.check:
        print("index.html のバージョンが古くなっています。python3 update_versions.py を実行してください。")
        return 1
    HTML.write_text(updated, encoding="utf-8")
    print("index.html を更新しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
