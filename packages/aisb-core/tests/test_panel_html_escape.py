"""パネルの HTML テンプレートに未エスケープの補間が増えていないことを確認する。ネットワーク不要。

API 応答や訪問者の入力を innerHTML に入れると、他の訪問者の画面でスクリプトが動く。
新しい値は escapeHtml を通すか、HTML を返す関数なら SAFE_HTML_VALUES に理由つきで足す。

実行: .venv/bin/python tests/test_panel_html_escape.py   (pytest でも可)
"""
import glob
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PATTERNS = [
    "packages/aisb-core/src/aisb_embed/static/**/*.js",
    "chrome-extension/modules/*.js",
    "chrome-extension/shared/*.js",
    "demo-legacy-system*/aisb_profile/static/**/*.js",
]
TAG = re.compile(r"<[a-zA-Z/!]")
ESCAPED = re.compile(r"^(window\.AISB\.domBase\.escapeHtml|ctx\.escapeHtml|escapeHtml|esc|encodeURIComponent)\(")
HTML_NAMED = re.compile(r"^[\w.]*([Hh]tml|HTML)$")
LITERAL = r"""("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')"""
LITERAL_ONLY = re.compile(f"^{LITERAL}$")
LITERAL_BRANCHES = re.compile(rf"^.*\?\s*{LITERAL}\s*:\s*{LITERAL}$", re.S)
# 数値か日付の文字列にしかならない式
NUMERIC = re.compile(
    r"^(Math\.round\([^`]*\)(\.toLocaleString\(\))?|Math\.max\([^`]*\)\.toFixed\(\d\)|\w+(\[\d\])?\.toFixed\(\d\)"
    r"|new Date\([^`]*\)\.toLocale\w*String\([^`]*\)|[\w.]+\.length|.*\.filter\(.*\)\.length)$"
)
# 内部でエスケープ済みの HTML を返す関数・変数と、コード内の定数・ループ添字
SAFE_HTML_VALUES = {
    "summaryBadges", "renderChart", "renderRegisterBtn", "renderRegisterArea", "renderStatusDistributionChart",
    "refLabel", "auditSummary", "items", "rows", "head", "cites", "bar", "legend", "dots", "AUDIT_NOTE",
    "W", "H", "PAD_L", "W - PAD_R", "areaPath", "linePath", "i", "missing.map",
}


class _Template:
    def __init__(self, start):
        self.start = start
        self.quasis = []
        self.exprs = []  # (start, end, 子テンプレート)


def _scan(s):
    """文字列・コメント・正規表現を読み飛ばしてテンプレートリテラルの木を返す。"""
    n = len(s)

    def code(i, in_expr, out):
        depth, prev = 0, ""
        while i < n:
            c = s[i]
            if c in "\"'":
                j = i + 1
                while s[j] != c:
                    j += 2 if s[j] == "\\" else 1
                i, prev = j + 1, "x"
            elif c == "`":
                t, i = template(i)
                out.append(t)
                prev = "x"
            elif s.startswith("//", i):
                i = s.index("\n", i)
            elif s.startswith("/*", i):
                i = s.index("*/", i) + 2
            elif c == "/" and (prev in ("", *"(,=:[!&|?{};+") or s[max(0, i - 7):i].rstrip().endswith("return")):
                j, in_class = i + 1, False
                while s[j] != "/" or in_class:
                    if s[j] == "\\":
                        j += 1
                    elif s[j] in "[]":
                        in_class = s[j] == "["
                    j += 1
                i, prev = j + 1, "x"
            else:
                if c == "{":
                    depth += 1
                elif c == "}":
                    if depth == 0 and in_expr:
                        return i
                    depth -= 1
                if not c.isspace():
                    prev = c
                i += 1
        return i

    def template(i):
        t = _Template(i)
        i += 1
        begin = i
        while s[i] != "`":
            if s[i] == "\\":
                i += 2
            elif s.startswith("${", i):
                t.quasis.append(s[begin:i])
                kids = []
                end = code(i + 2, True, kids)
                t.exprs.append((i + 2, end, kids))
                i = begin = end + 1
            else:
                i += 1
        t.quasis.append(s[begin:i])
        return t, i + 1

    tops = []
    code(0, False, tops)
    return tops


def _is_safe(expr):
    return bool(
        ESCAPED.match(expr) or LITERAL_ONLY.match(expr) or LITERAL_BRANCHES.match(expr)
        or HTML_NAMED.match(expr) or NUMERIC.match(expr)
        or any(expr == v or expr.startswith(v + "(") or expr.startswith(v + ".") for v in SAFE_HTML_VALUES)
    )


def unescaped_interpolations(source):
    found = []

    def walk(t, in_html):
        html = in_html or any(TAG.search(q) for q in t.quasis) or re.search(r"innerHTML\s*\+?=\s*$", source[:t.start])
        for start, end, kids in t.exprs:
            if kids:
                for k in kids:
                    walk(k, html)
            elif html and not _is_safe(source[start:end].strip()):
                found.append((source.count("\n", 0, start) + 1, source[start:end].strip()))

    for t in _scan(source):
        walk(t, False)
    return found


def _panel_files():
    files = []
    for pattern in PATTERNS:
        files += glob.glob(os.path.join(ROOT, pattern), recursive=True)
    return sorted(set(files))


def test_scanner_finds_unescaped_values():
    src = "el.innerHTML = `<b>${n.title}</b>${esc(n.body)}`; fetch(`${base}/x/${id}`); el.innerHTML = `e: ${err}`;"
    assert [e for _, e in unescaped_interpolations(src)] == ["n.title", "err"]
    nested = "x.innerHTML = `<ul>${list.map((a) => `<li>${a.name}</li>`).join('')}</ul>`;"
    assert [e for _, e in unescaped_interpolations(nested)] == ["a.name"]


def test_no_unescaped_interpolation_in_panels():
    files = _panel_files()
    assert len(files) > 40, files
    problems = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            for line, expr in unescaped_interpolations(f.read()):
                problems.append(f"{os.path.relpath(path, ROOT)}:{line}: {expr[:80]}")
    assert not problems, "\n".join(problems)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
