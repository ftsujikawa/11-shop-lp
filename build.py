#!/usr/bin/env python3
"""script.js（編集用の元ファイル）から、最小化した script.min.js を作る（標準ライブラリのみ）。
最後に update_versions.py を呼んで、index.html の ?v= も更新する。

  python3 build.py

script.js を編集したら、必ずこれを実行する。script.min.js は直接編集しない。

最小化の内容（安全側に倒した控えめなもの）:
  - コメント（// と /* */）を消す
  - 行頭の字下げ・行末の空白・空行を消す
  - 記号の前後の空白を消す（識別子どうしの間など、必要な空白は残す）
  - 文字列・テンプレートリテラル・正規表現の中身は一切変えない
  - 改行は残す（自動セミコロン挿入で意味が変わるのを防ぐため）

使わないコードの削除:
  - /* build:remove-start */ 〜 /* build:remove-end */ の範囲は script.min.js に含めない
    （Node での動作確認用の module.exports など、ブラウザでは使わないコード）
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "script.js"
DEST = ROOT / "script.min.js"

REMOVE_BLOCK = re.compile(r"/\* build:remove-start\b.*?/\* build:remove-end \*/", re.DOTALL)

IDENT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$")
# この語の直後の / は割り算ではなく正規表現の始まり
REGEX_KEYWORDS = {"return", "typeof", "instanceof", "in", "of", "new", "delete",
                  "void", "throw", "case", "do", "else", "yield", "await"}


class Minifier:
    def __init__(self, src: str) -> None:
        self.s = src
        self.i = 0
        self.out: list[str] = []
        self.pending_space = False
        self.pending_newline = False

    # ---- 出力 ----------------------------------------------------------
    def last_char(self) -> str:
        for chunk in reversed(self.out):
            if chunk:
                return chunk[-1]
        return ""

    def last_word(self) -> str:
        text = "".join(self.out[-20:])
        j = len(text)
        while j > 0 and text[j - 1] in IDENT:
            j -= 1
        return text[j:]

    def emit(self, token: str) -> None:
        """コードのトークンを出力する。保留中の空白・改行を必要なときだけ入れる。"""
        prev = self.last_char()
        if self.pending_newline and prev and prev != "\n":
            self.out.append("\n")
        elif self.pending_space and prev and prev != "\n":
            nxt = token[0]
            if (prev in IDENT and nxt in IDENT) \
                    or (prev in "+-" and nxt in "+-") \
                    or (prev == "/" and nxt == "/"):
                self.out.append(" ")
        self.pending_space = False
        self.pending_newline = False
        self.out.append(token)

    # ---- 読み取り ------------------------------------------------------
    def regex_allowed(self) -> bool:
        prev = self.last_char()
        if prev == "" or prev == "\n" and not self.out[-1].strip():
            return True
        if prev in "(,=:[!&|?{};+-*%<>~^\n":
            return True
        return self.last_word() in REGEX_KEYWORDS

    def read_string(self, quote: str) -> str:
        s, start = self.s, self.i
        self.i += 1
        while s[self.i] != quote:
            if s[self.i] == "\\":
                self.i += 1
            elif s[self.i] == "\n":
                raise SyntaxError(f"文字列が閉じていません（{start} 文字目）")
            self.i += 1
        self.i += 1
        return s[start:self.i]

    def read_template(self) -> str:
        """テンプレートリテラル。${ ... } の中はコードとして再帰的に最小化する。"""
        s = self.s
        parts = ["`"]
        self.i += 1
        while s[self.i] != "`":
            if s[self.i] == "\\":
                parts.append(s[self.i:self.i + 2])
                self.i += 2
            elif s.startswith("${", self.i):
                self.i += 2
                inner = Minifier(s)
                inner.i = self.i
                code = inner.run(stop_at_brace=True)
                self.i = inner.i + 1  # 閉じ } を飛ばす
                parts.append("${" + code + "}")
            else:
                parts.append(s[self.i])
                self.i += 1
        self.i += 1
        parts.append("`")
        return "".join(parts)

    def read_regex(self) -> str:
        s, start = self.s, self.i
        self.i += 1
        in_class = False
        while True:
            c = s[self.i]
            if c == "\\":
                self.i += 2
                continue
            if c == "\n":
                raise SyntaxError(f"正規表現が閉じていません（{start} 文字目）")
            if c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                self.i += 1
                break
            self.i += 1
        while self.i < len(s) and s[self.i] in IDENT:  # フラグ（g, i など）
            self.i += 1
        return s[start:self.i]

    def run(self, stop_at_brace: bool = False) -> str:
        s = self.s
        depth = 0
        while self.i < len(s):
            c = s[self.i]
            if c == "\n":
                self.pending_newline = True
                self.i += 1
            elif c in " \t\r":
                self.pending_space = True
                self.i += 1
            elif s.startswith("//", self.i):
                end = s.find("\n", self.i)
                self.i = len(s) if end == -1 else end
            elif s.startswith("/*", self.i):
                end = s.find("*/", self.i + 2)
                if end == -1:
                    raise SyntaxError("コメントが閉じていません")
                if "\n" in s[self.i:end]:
                    self.pending_newline = True
                else:
                    self.pending_space = True
                self.i = end + 2
            elif c in "'\"":
                self.emit(self.read_string(c))
            elif c == "`":
                self.emit(self.read_template())
            elif c == "/" and self.regex_allowed():
                self.emit(self.read_regex())
            elif c in IDENT:
                j = self.i
                while j < len(s) and s[j] in IDENT:
                    j += 1
                self.emit(s[self.i:j])
                self.i = j
            else:
                if stop_at_brace:
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        if depth == 0:
                            return "".join(self.out)
                        depth -= 1
                self.emit(c)
                self.i += 1
        if stop_at_brace:
            raise SyntaxError("テンプレートリテラルの ${ が閉じていません")
        return "".join(self.out).strip() + "\n"


def main() -> int:
    src = SRC.read_text(encoding="utf-8")
    src_for_browser, removed = REMOVE_BLOCK.subn("", src)
    if removed:
        print(f"ブラウザで使わないコードを {removed} か所削除", flush=True)
    minified = Minifier(src_for_browser).run()
    header = "/* script.js から build.py で生成。直接編集しない */\n"
    DEST.write_text(header + minified, encoding="utf-8")

    before, after = len(src.encode()), len((header + minified).encode())
    print(f"{SRC.name} {before:,} B → {DEST.name} {after:,} B（{100 - after * 100 // before}% 削減）", flush=True)

    # Node.js があれば構文チェック
    try:
        r = subprocess.run(["node", "--check", str(DEST)], capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            print("構文エラーのため中止しました。", file=sys.stderr)
            return 1
        print("構文チェック OK（node --check）", flush=True)
    except FileNotFoundError:
        print("※ Node.js が無いため構文チェックは省略しました")

    return subprocess.call([sys.executable, str(ROOT / "update_versions.py")])


if __name__ == "__main__":
    sys.exit(main())
