#!/usr/bin/env python3
"""キャッシュと圧縮を設定して配信する、ローカル確認用のサーバー（標準ライブラリのみ）。

  python3 serve.py          # http://localhost:8000/
  python3 serve.py 8080     # ポートを指定

公開するサーバーでも、同じ設定にする:

キャッシュ
  - バージョン付き（?v=...）の CSS / JS / 画像 … 1 年。中身が変われば URL が変わる
  - HTML                                       … 毎回サーバーに更新を確認（no-cache）
  - それ以外                                   … 1 時間

レイテンシ
  - テキスト（HTML / CSS / JS / SVG など）は gzip で圧縮して送る
  - HTTP/1.1 の持続的接続で、HTML の後の CSS / JS を同じ接続で取得できる
  - リダイレクトはしない（/ には index.html を直接返す）
"""

from __future__ import annotations

import email.utils
import gzip
import os
import sys
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent

ONE_YEAR = 60 * 60 * 24 * 365
STATIC_EXT = {".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".avif", ".ico", ".woff2"}

# 圧縮して送るテキスト形式（Content-Type に charset も付ける）
TEXT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}
MIN_COMPRESS_BYTES = 256  # これより小さいものは圧縮しても得にならない

# 圧縮結果のキャッシュ（パス → (更新時刻, 圧縮後のバイト列)）。リクエストごとに圧縮し直さない
_gzip_cache: dict[str, tuple[float, bytes]] = {}


def cache_control(url_path: str) -> str:
    parts = urlsplit(url_path)
    path = parts.path
    if path.endswith("/") or path.endswith(".html"):
        return "no-cache"
    if Path(path).suffix.lower() in STATIC_EXT and "v" in parse_qs(parts.query):
        return f"public, max-age={ONE_YEAR}, immutable"
    return "public, max-age=3600"


def gzipped(path: str, mtime: float) -> bytes:
    hit = _gzip_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(path, "rb") as f:
        body = gzip.compress(f.read(), compresslevel=9, mtime=0)
    _gzip_cache[path] = (mtime, body)
    return body


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # 持続的接続（Content-Length は常に付ける）

    def end_headers(self) -> None:
        self.send_header("Cache-Control", cache_control(self.path))
        super().end_headers()

    def _text_file(self) -> tuple[str, str] | None:
        """圧縮して送れるテキストファイルなら (ファイルパス, Content-Type) を返す。"""
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            if not urlsplit(self.path).path.endswith("/"):
                return None  # ディレクトリの末尾スラッシュ補完は標準の動作に任せる
            path = os.path.join(path, "index.html")
        ctype = TEXT_TYPES.get(Path(path).suffix.lower())
        if ctype and os.path.isfile(path):
            return path, ctype
        return None

    def _accepts_gzip(self) -> bool:
        enc = self.headers.get("Accept-Encoding", "")
        return any(p.split(";")[0].strip().lower() == "gzip" for p in enc.split(","))

    def _send_text(self, head_only: bool) -> bool:
        target = self._text_file()
        if target is None:
            return False
        path, ctype = target
        st = os.stat(path)
        last_modified = email.utils.formatdate(st.st_mtime, usegmt=True)

        # 変更がなければ 304（本文なし）
        ims = self.headers.get("If-Modified-Since")
        if ims:
            try:
                if int(st.st_mtime) <= email.utils.parsedate_to_datetime(ims).timestamp():
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    self.send_header("Last-Modified", last_modified)
                    self.send_header("Vary", "Accept-Encoding")
                    self.end_headers()
                    return True
            except (TypeError, ValueError, OverflowError):
                pass

        use_gzip = self._accepts_gzip() and st.st_size >= MIN_COMPRESS_BYTES
        if use_gzip:
            body = gzipped(path, st.st_mtime)
        else:
            with open(path, "rb") as f:
                body = f.read()

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Last-Modified", last_modified)
        self.send_header("Vary", "Accept-Encoding")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)
        return True

    def do_GET(self) -> None:
        if not self._send_text(head_only=False):
            super().do_GET()

    def do_HEAD(self) -> None:
        if not self._send_text(head_only=True):
            super().do_HEAD()


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    handler = partial(Handler, directory=str(ROOT))
    with ThreadingHTTPServer(("", port), handler) as httpd:
        print(f"http://localhost:{port}/ で配信中（Ctrl+C で停止）")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
