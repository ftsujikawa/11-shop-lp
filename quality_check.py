#!/usr/bin/env python3
"""ランディングページの品質チェック（標準ライブラリのみ・読み取り専用）

チェック項目:
  1. 禁止語（裏付けのない誇大表現）
  2. 見出しの階層
  3. 入力欄のラベル
  4. 画像の alt
  5. 構造化データ（JSON-LD）
  6. 文字色のコントラスト（WCAG 2.x AA）

使い方:
  python3 quality_check.py            # index.html / style.css / script.js をチェック
  python3 quality_check.py --dir PATH # 別フォルダをチェック

問題が見つかったら「要確認」として一覧にし、終了コード 1 を返す。
ファイルは一切書き換えない。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

# 裏付けのない誇大表現・比較表現。必要に応じて追加する。
FORBIDDEN_WORDS = [
    "一番", "いちばん", "No.1", "No1", "ナンバーワン", "ナンバー1", "Ｎｏ．１",
    "最高", "最高級", "最上級", "最強", "最安", "最安値", "最大級", "最良",
    "日本一", "世界一", "地域一", "県内一", "町内一", "業界初", "日本初", "世界初",
    "唯一", "絶対", "完璧", "究極", "No.1", "トップクラス", "どこよりも",
    "人気", "大人気", "話題の", "行列",  # shop.md に裏付けがない
]

# 構造化データで期待する型と項目（shop.md にある情報で埋められるもの）
EXPECTED_LD_TYPES = {"Bakery", "LocalBusiness", "FoodEstablishment"}
EXPECTED_LD_KEYS = ["name", "address", "telephone", "openingHoursSpecification"]

# WCAG AA
CONTRAST_NORMAL = 4.5
CONTRAST_LARGE = 3.0

ROOT_FONT_PX = 16.0


@dataclass
class Finding:
    category: str
    location: str
    message: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    passed: dict[str, str] = field(default_factory=dict)

    def add(self, category: str, location: str, message: str) -> None:
        self.findings.append(Finding(category, location, message))


CATEGORIES = [
    "禁止語",
    "見出しの階層",
    "入力欄のラベル",
    "画像の alt",
    "構造化データ",
    "文字色のコントラスト",
]


# ---------------------------------------------------------------------------
# HTML の解析
# ---------------------------------------------------------------------------

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
             "meta", "source", "track", "wbr"}


@dataclass
class Element:
    tag: str
    attrs: dict[str, str]
    line: int
    parent: "Element | None" = None
    children: list["Element"] = field(default_factory=list)
    text: str = ""  # 直下＋子孫のテキスト（閉じタグ時に確定）


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#root", {}, 0)
        self.stack: list[Element] = [self.root]
        self.elements: list[Element] = []
        self.text_chunks: list[tuple[int, str, str]] = []  # (line, 親タグ, テキスト)

    def handle_starttag(self, tag, attrs):
        el = Element(tag, {k: (v or "") for k, v in attrs}, self.getpos()[0], self.stack[-1])
        self.stack[-1].children.append(el)
        self.elements.append(el)
        if tag not in VOID_TAGS:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not data.strip():
            return
        for el in self.stack[1:]:
            el.text += data
        self.text_chunks.append((self.getpos()[0], self.stack[-1].tag, data))


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# 1. 禁止語
# ---------------------------------------------------------------------------

def check_forbidden_words(report: Report, html_path: Path, parser: PageParser,
                          js_path: Path | None) -> None:
    cat = "禁止語"
    words = sorted(set(FORBIDDEN_WORDS), key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(w) for w in words), re.IGNORECASE)
    before = len(report.findings)

    def scan(text: str, where: str) -> None:
        for m in pattern.finditer(text):
            start = max(0, m.start() - 12)
            context = norm(text[start:m.end() + 12])
            report.add(cat, where, f"「{m.group(0)}」…{context}…")

    # 表示テキスト（script / style の中身は除外）
    for line, tag, text in parser.text_chunks:
        if tag in ("script", "style"):
            continue
        scan(text, f"{html_path.name}:{line}")

    # 属性（alt / title / placeholder / aria-label / meta content）
    for el in parser.elements:
        for attr in ("alt", "title", "placeholder", "aria-label"):
            if attr in el.attrs:
                scan(el.attrs[attr], f"{html_path.name}:{el.line} [{attr}]")
        if el.tag == "meta" and "content" in el.attrs:
            scan(el.attrs["content"], f"{html_path.name}:{el.line} [meta]")

    # JavaScript が画面に出す文字列（コメントは除外）
    if js_path and js_path.exists():
        for i, raw in enumerate(js_path.read_text(encoding="utf-8").splitlines(), 1):
            code = raw.split("//", 1)[0]
            if code.lstrip().startswith(("*", "/*")):
                continue
            for lit in re.findall(r"'([^']*)'|`([^`]*)`|\"([^\"]*)\"", code):
                scan("".join(lit), f"{js_path.name}:{i}")

    if len(report.findings) == before:
        report.passed[cat] = f"{len(words)} 語を HTML・属性・JS の文字列から検索し、該当なし"


# ---------------------------------------------------------------------------
# 2. 見出しの階層
# ---------------------------------------------------------------------------

def check_headings(report: Report, html_path: Path, parser: PageParser) -> None:
    cat = "見出しの階層"
    before = len(report.findings)
    headings = [el for el in parser.elements if re.fullmatch(r"h[1-6]", el.tag)]

    h1s = [h for h in headings if h.tag == "h1"]
    if len(h1s) == 0:
        report.add(cat, html_path.name, "h1 がありません")
    elif len(h1s) > 1:
        lines = ", ".join(str(h.line) for h in h1s)
        report.add(cat, html_path.name, f"h1 が {len(h1s)} 個あります（行 {lines}）")

    if headings and headings[0].tag != "h1":
        report.add(cat, f"{html_path.name}:{headings[0].line}",
                   f"最初の見出しが {headings[0].tag} です（h1 から始まっていません）")

    prev = 0
    for h in headings:
        level = int(h.tag[1])
        if prev and level > prev + 1:
            report.add(cat, f"{html_path.name}:{h.line}",
                       f"h{prev} の次が {h.tag} で、階層が飛んでいます：「{norm(h.text)}」")
        if not norm(h.text):
            report.add(cat, f"{html_path.name}:{h.line}", f"{h.tag} が空です")
        prev = level

    if len(report.findings) == before:
        outline = " → ".join(h.tag for h in headings)
        report.passed[cat] = f"見出し {len(headings)} 個、h1 は 1 個、飛びなし（{outline}）"


# ---------------------------------------------------------------------------
# 3. 入力欄のラベル
# ---------------------------------------------------------------------------

def check_labels(report: Report, html_path: Path, parser: PageParser) -> None:
    cat = "入力欄のラベル"
    before = len(report.findings)
    skip_types = {"hidden", "submit", "button", "reset", "image"}

    label_for = {el.attrs.get("for") for el in parser.elements
                 if el.tag == "label" and el.attrs.get("for")}
    ids = {el.attrs["id"]: el for el in parser.elements if el.attrs.get("id")}

    controls = [el for el in parser.elements
                if el.tag in ("input", "textarea", "select")
                and el.attrs.get("type", "text") not in skip_types]

    for el in controls:
        name = el.attrs.get("id") or el.attrs.get("name") or el.tag
        where = f"{html_path.name}:{el.line}"
        has_label = False

        if el.attrs.get("id") and el.attrs["id"] in label_for:
            label = next(l for l in parser.elements
                         if l.tag == "label" and l.attrs.get("for") == el.attrs["id"])
            if norm(label.text):
                has_label = True
            else:
                report.add(cat, where, f"#{name} のラベルが空です")
                continue

        p = el.parent
        while p is not None and not has_label:
            if p.tag == "label" and norm(p.text):
                has_label = True
            p = p.parent

        if norm(el.attrs.get("aria-label", "")):
            has_label = True
        for ref in el.attrs.get("aria-labelledby", "").split():
            if ref in ids and norm(ids[ref].text):
                has_label = True

        if not has_label:
            hint = "（placeholder だけではラベルになりません）" if el.attrs.get("placeholder") else ""
            report.add(cat, where, f"{el.tag}#{name} にラベルがありません{hint}")

        for ref in el.attrs.get("aria-describedby", "").split():
            if ref not in ids:
                report.add(cat, where, f"#{name} の aria-describedby が存在しない id「{ref}」を指しています")

    if len(report.findings) == before:
        report.passed[cat] = f"入力欄 {len(controls)} 個すべてにラベルあり"


# ---------------------------------------------------------------------------
# 4. 画像の alt
# ---------------------------------------------------------------------------

def check_alt(report: Report, html_path: Path, parser: PageParser,
              css_text: str) -> None:
    cat = "画像の alt"
    before = len(report.findings)
    imgs = [el for el in parser.elements if el.tag == "img"]
    inputs_img = [el for el in parser.elements
                  if el.tag == "input" and el.attrs.get("type") == "image"]

    for el in imgs + inputs_img:
        src = el.attrs.get("src", "(src なし)")
        where = f"{html_path.name}:{el.line}"
        if "alt" not in el.attrs:
            report.add(cat, where, f"alt 属性がありません：{src}")
        elif not el.attrs["alt"].strip() and el.attrs.get("role") != "presentation":
            report.add(cat, where, f"alt が空です（装飾画像なら問題なし）：{src}")
        elif re.search(r"\.(jpe?g|png|gif|webp|svg)$|^(画像|写真|image|img)$",
                       el.attrs["alt"].strip(), re.IGNORECASE):
            report.add(cat, where, f"alt がファイル名や「画像」だけです：「{el.attrs['alt']}」")

    for el in parser.elements:
        if el.tag == "svg" and el.attrs.get("aria-hidden") != "true" \
                and not el.attrs.get("aria-label") and not any(c.tag == "title" for c in el.children):
            report.add(cat, f"{html_path.name}:{el.line}",
                       "インライン SVG に title / aria-label がありません")

    css_images = re.findall(r"url\(([^)]+)\)", css_text)
    if len(report.findings) == before:
        if imgs or inputs_img:
            report.passed[cat] = f"画像 {len(imgs) + len(inputs_img)} 個すべてに適切な alt あり"
        else:
            note = f"（CSS の背景画像 {len(css_images)} 個は対象外）" if css_images else ""
            report.passed[cat] = f"img 要素なし。チェック対象がありません{note}"


# ---------------------------------------------------------------------------
# 5. 構造化データ
# ---------------------------------------------------------------------------

def check_structured_data(report: Report, html_path: Path, html_text: str) -> None:
    cat = "構造化データ"
    before = len(report.findings)
    blocks = re.findall(
        r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html_text, re.DOTALL | re.IGNORECASE)

    if not blocks:
        report.add(cat, html_path.name,
                   "JSON-LD（<script type=\"application/ld+json\">）がありません。"
                   "店名・住所・電話・営業時間を Bakery 型で記述できます")
        return

    found_types: set[str] = set()
    for i, raw in enumerate(blocks, 1):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            report.add(cat, f"{html_path.name} JSON-LD #{i}", f"JSON として読めません：{e}")
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for item in items:
            if not isinstance(item, dict):
                continue
            types = item.get("@type", [])
            types = {types} if isinstance(types, str) else set(types)
            found_types |= types
            if "@context" not in item and "@context" not in data:
                report.add(cat, f"{html_path.name} JSON-LD #{i}", "@context がありません")
            if types & EXPECTED_LD_TYPES:
                for key in EXPECTED_LD_KEYS:
                    if key not in item and not (key == "openingHoursSpecification"
                                                and "openingHours" in item):
                        report.add(cat, f"{html_path.name} JSON-LD #{i}",
                                   f"{'/'.join(sorted(types))} に {key} がありません")

    if not found_types & EXPECTED_LD_TYPES:
        report.add(cat, html_path.name,
                   f"店舗を表す型（{', '.join(sorted(EXPECTED_LD_TYPES))}）がありません"
                   f"（見つかった型：{', '.join(sorted(found_types)) or 'なし'}）")

    if len(report.findings) == before:
        report.passed[cat] = f"JSON-LD {len(blocks)} 個、必要な項目あり"


# ---------------------------------------------------------------------------
# 6. 文字色のコントラスト
# ---------------------------------------------------------------------------

NAMED_COLORS = {"white": "#ffffff", "black": "#000000"}


def parse_color(value: str) -> tuple[float, float, float] | None:
    v = value.strip().lower()
    v = NAMED_COLORS.get(v, v)
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    m = re.fullmatch(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+%?))?\s*\)", v)
    if m:
        if m.group(4) and m.group(4) not in ("1", "1.0", "100%"):
            return None  # 半透明は背景次第なので扱わない
        return tuple(float(m.group(i)) for i in (1, 2, 3))  # type: ignore[return-value]
    return None


def luminance(rgb: tuple[float, float, float]) -> float:
    def ch(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@dataclass
class CssRule:
    selector: str
    decls: dict[str, str]
    line: int
    media: str
    source: str = ""


def parse_css(text: str, source: str = "", start_line: int = 1) -> list[CssRule]:
    """入れ子（@media）を 1 段だけ展開する簡易パーサ。"""
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)
    rules: list[CssRule] = []

    def walk(chunk: str, offset_line: int, media: str) -> None:
        i = 0
        while i < len(chunk):
            brace = chunk.find("{", i)
            if brace == -1:
                return
            selector = chunk[i:brace].strip()
            depth, j = 1, brace + 1
            while j < len(chunk) and depth:
                depth += {"{": 1, "}": -1}.get(chunk[j], 0)
                j += 1
            body = chunk[brace + 1:j - 1]
            line = offset_line + chunk[:brace].count("\n")
            if selector.startswith("@media"):
                walk(body, line, selector)
            elif not selector.startswith("@"):
                decls = {}
                for d in body.split(";"):
                    if ":" in d:
                        k, v = d.split(":", 1)
                        decls[k.strip().lower()] = v.strip()
                rules.append(CssRule(norm(selector), decls, line, media, source))
            i = j

    walk(text, start_line, "")
    return rules


def resolve_vars(value: str, variables: dict[str, str]) -> str:
    for _ in range(5):
        new = re.sub(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)",
                     lambda m: variables.get(m.group(1), m.group(2) or ""), value)
        if new == value:
            break
        value = new
    return value.replace("!important", "").strip()


def font_px(value: str | None) -> float | None:
    if not value:
        return None
    m = re.match(r"([\d.]+)(rem|em|px)", value)
    if m:
        n = float(m.group(1))
        return n if m.group(2) == "px" else n * ROOT_FONT_PX
    m = re.match(r"clamp\(\s*([\d.]+)(rem|px)", value)  # clamp は最小値で判定
    if m:
        n = float(m.group(1))
        return n if m.group(2) == "px" else n * ROOT_FONT_PX
    return None


def check_contrast(report: Report, sources: list[tuple[str, str, int]]) -> None:
    """sources: (表示名, CSS テキスト, 開始行) のリスト。HTML 内の <style> と外部 CSS をまとめて扱う。"""
    cat = "文字色のコントラスト"
    before = len(report.findings)
    rules = [r for name, text, start in sources for r in parse_css(text, name, start)]

    variables: dict[str, str] = {}
    for r in rules:
        if r.selector == ":root" and not r.media:
            variables.update({k: v for k, v in r.decls.items() if k.startswith("--")})

    def get_bg(decls: dict[str, str]) -> str | None:
        for key in ("background-color", "background"):
            if key in decls:
                v = resolve_vars(decls[key], variables)
                if parse_color(v):
                    return v
                if v in ("transparent", "none"):
                    return None
        return None

    # 背景を指定していない規則は、ページで使っている背景色（body とセクション）と照合する
    body_rule = next((r for r in rules if r.selector == "body"), None)
    page_bgs = []
    if body_rule and get_bg(body_rule.decls):
        page_bgs.append(("body の背景", get_bg(body_rule.decls)))
    surface = variables.get("--surface")
    if surface and parse_color(surface):
        page_bgs.append(("白いセクション・カードの背景", surface))
    if not page_bgs:
        page_bgs.append(("白（既定）", "#ffffff"))

    # 「.a, .b」のようなまとめ書きも 1 つずつ引けるようにする（後勝ちで宣言を合成）
    by_selector: dict[str, CssRule] = {}
    for r in rules:
        if r.media:
            continue
        for part in (p.strip() for p in r.selector.split(",")):
            prev = by_selector.get(part)
            merged = {**prev.decls, **r.decls} if prev else dict(r.decls)
            by_selector[part] = CssRule(part, merged, r.line, "")

    def own_or_shared(selector: str, prop: str) -> str | None:
        rule = by_selector.get(selector)
        return rule.decls.get(prop) if rule else None

    def inherited(selector: str, prop: str) -> str | None:
        """子孫セレクタ（.a .b）や疑似要素（.a::before）は、親側の規則から値を引き継ぐ。"""
        sel = re.sub(r"::?(before|after)$", "", selector)
        candidates = [sel] if sel != selector else []
        parts = sel.split(" ")
        candidates += [" ".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]
        for c in candidates:
            rule = by_selector.get(c)
            if rule and prop in rule.decls:
                return rule.decls[prop]
        return None

    # 見出しタグの既定（太字）
    def default_bold(selector: str) -> bool:
        return any(re.search(rf"(^|\s){h}\b", selector) for h in ("h1", "h2", "h3", "h4", "h5", "h6"))

    checked = 0
    for r in rules:
        if "color" not in r.decls:
            continue
        fg_raw = resolve_vars(r.decls["color"], variables)
        fg = parse_color(fg_raw)
        if fg is None:
            continue  # inherit / currentColor など

        size_raw = (r.decls.get("font-size") or own_or_shared(r.selector, "font-size")
                    or inherited(r.selector, "font-size"))
        size = font_px(size_raw)
        weight = (r.decls.get("font-weight") or own_or_shared(r.selector, "font-weight")
                  or inherited(r.selector, "font-weight") or "")
        bold = weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 700) \
            or (not weight and default_bold(r.selector))
        large = size is not None and (size >= 24 or (bold and size >= 18.66))

        # ::before / ::after で記号だけを出す場合は、文字ではなく図形（3:1）として扱う
        content = r.decls.get("content", "")
        graphic = bool(re.fullmatch(r"[\"'][^\w぀-ヿ一-鿿]+[\"']", content.strip()))

        need = CONTRAST_LARGE if (large or graphic) else CONTRAST_NORMAL
        kind = "記号（図形扱い）" if graphic else ("大きい文字" if large else "通常の文字")
        size_note = f"{size:.0f}px" if size else "16px 想定"

        own_bg = get_bg(r.decls)
        candidates = [("同じ規則の背景", own_bg)] if own_bg else page_bgs
        media = f" {r.media}" if r.media else ""
        fails = []
        for bg_name, bg_raw in candidates:
            checked += 1
            ratio = contrast(fg, parse_color(bg_raw))  # type: ignore[arg-type]
            if ratio < need:
                fails.append(f"{bg_name} {bg_raw} で {ratio:.2f}:1")
        if fails:
            report.add(cat, f"{r.source}:{r.line}{media}",
                       f"{r.selector}：文字色 {fg_raw} が " + "、".join(fails)
                       + f"（{kind}・{size_note}、基準 {need}:1 以上）")

    if len(report.findings) == before:
        report.passed[cat] = f"{checked} 組の文字色と背景色がすべて基準以上"


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

def print_report(report: Report) -> None:
    total = len(report.findings)
    print("=" * 64)
    print(" 品質チェック結果")
    print("=" * 64)
    print()
    print("■ 概要")
    for cat in CATEGORIES:
        n = sum(1 for f in report.findings if f.category == cat)
        status = f"要確認 {n} 件" if n else "OK"
        print(f"  {cat:<12}\t{status}")
    print(f"  {'合計':<12}\t要確認 {total} 件")
    print()

    if total:
        print(f"■ 要確認（{total} 件）")
        no = 0
        for cat in CATEGORIES:
            items = [f for f in report.findings if f.category == cat]
            if not items:
                continue
            print(f"\n  [{cat}] {len(items)} 件")
            for f in items:
                no += 1
                print(f"   {no:>2}. {f.location}")
                print(f"       {f.message}")
        print()

    if report.passed:
        print("■ 問題なし")
        for cat in CATEGORIES:
            if cat in report.passed:
                print(f"  [{cat}] {report.passed[cat]}")
        print()

    print("※ コントラストは CSS（index.html の <style> と style.css）を簡易解析した推定です。背景を指定していない規則は")
    print("  ページの背景色と照合しています。最終確認はブラウザの開発者ツールで行ってください。")


def main() -> int:
    ap = argparse.ArgumentParser(description="LP の品質チェック（読み取り専用）")
    ap.add_argument("--dir", default=Path(__file__).resolve().parent, type=Path)
    ap.add_argument("--html", default="index.html")
    ap.add_argument("--css", default="style.css")
    ap.add_argument("--js", default="script.js")
    args = ap.parse_args()

    html_path = args.dir / args.html
    css_path = args.dir / args.css
    js_path = args.dir / args.js
    if not html_path.exists():
        print(f"見つかりません：{html_path}", file=sys.stderr)
        return 2

    html_text = html_path.read_text(encoding="utf-8")
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    # HTML に直接書いた <style>（クリティカル CSS）も対象にする。行番号は HTML の行で表示
    css_sources: list[tuple[str, str, int]] = []
    for m in re.finditer(r"<style[^>]*>(.*?)</style>", html_text, re.DOTALL | re.IGNORECASE):
        start = html_text[:m.start(1)].count("\n") + 1
        css_sources.append((f"{html_path.name} <style>", m.group(1), start))
    if css_text:
        css_sources.append((css_path.name, css_text, 1))
    all_css = "\n".join(text for _, text, _ in css_sources)

    parser = PageParser()
    parser.feed(html_text)

    report = Report()
    check_forbidden_words(report, html_path, parser, js_path)
    check_headings(report, html_path, parser)
    check_labels(report, html_path, parser)
    check_alt(report, html_path, parser, all_css)
    check_structured_data(report, html_path, html_text)
    if css_sources:
        check_contrast(report, css_sources)
    else:
        report.add("文字色のコントラスト", args.css, "CSS が見つかりません")

    print_report(report)
    return 1 if report.findings else 0


if __name__ == "__main__":
    sys.exit(main())
