"""产物外链硬断言的常驻落点（断网可开）。

纪律（plan/03 §4.2）：HTML 必须**内联 CSS、零外链**，断网可开。
本断言**常驻在渲染出口**——`markdown.render_markdown()` 与 `html.render_html()`
每次返回前都调用它，**不是"测试里验一次"**。这样"某次改动偷偷引入一个 CDN 字体"
会在渲染当场炸掉，而不是等到有人真的断网打开报告时才发现。

本模块零判定：它只做**字符串形态检查**，不读规则包、不算任何比率。
"""

# 会触发外部请求的构造（一律小写比较）。列全而非抽查：漏一项就等于给外链留一扇门。
_EXTERNAL_TOKENS = (
    "<link",
    "<script",
    "<img",
    "<iframe",
    "<object",
    "<embed",
    "<video",
    "<audio",
    "<source",
    "<form",
    "<base",
    "<input",
    "@import",
    "url(",
    "src=",
    "href=",
    "http://",
    "https://",
    '="//',
    "='//",
)


def find_external_tokens(text):
    """返回文本中命中的外链构造（排序去重，便于断言失败时逐项列出）。"""
    lowered = (text or "").lower()
    return sorted(set(token for token in _EXTERNAL_TOKENS if token in lowered))


def assert_no_external_resources(text):
    """渲染出口硬断言：产物含任何外链构造即抛错（断网不可开 = 交付不达标）。"""
    hits = find_external_tokens(text)
    if hits:
        raise AssertionError(
            "产物含外部资源引用，断网不可开：{0}".format(", ".join(hits))
        )
    return text
