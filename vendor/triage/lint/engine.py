"""Triage Design System — lint engine.

Pure functions so the CLI and tests share one implementation. The engine takes
a parsed system spec (tokens, rename map, rule catalogue) and a file's text and
returns findings.
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SEVERITIES = ("info", "warning", "error")


class Finding(object):
    def __init__(self, rule, severity, path, line, message, excerpt="", fix=""):
        self.rule = rule
        self.severity = severity
        self.path = path
        self.line = line
        self.message = message
        self.excerpt = excerpt.strip()
        self.fix = fix

    def as_dict(self):
        return {"rule": self.rule, "severity": self.severity, "file": self.path,
                "line": self.line, "message": self.message, "excerpt": self.excerpt, "fix": self.fix}


class Spec(object):
    def __init__(self, root=ROOT, config=None):
        self.root = root
        cfg = config or {}
        with open(os.path.join(root, "spec", "rules.json")) as fh:
            self.rules = {r["id"]: r for r in json.load(fh)["rules"]}
        with open(os.path.join(root, "tokens", "tokens.json")) as fh:
            doc = json.load(fh)
        with open(os.path.join(root, "rename-map.json")) as fh:
            rmap = json.load(fh)

        self.token_values = {}
        self.token_names = set()
        for name, tok in doc["color"].items():
            if name.startswith("$") or not isinstance(tok, dict):
                continue
            self.token_names.add(name)
            val = tok.get("$value")
            if isinstance(val, dict) and "hex" in val and val.get("alpha") is None:
                self.token_values[_norm_hex(val["hex"])] = name
        self.spacing = {t["$value"]["value"] for t in doc["spacing"].values()
                        if isinstance(t, dict) and "$value" in t}
        self.spacing |= set(cfg.get("spacingScale", [])) | {0, 1, 2}
        self.durations = {t["$value"]["value"] for t in doc["motion"]["duration"].values()
                          if isinstance(t, dict) and "$value" in t}
        self.durations |= {0, 1} | set(cfg.get("durations", []))
        self.zindex = {t["$value"] for t in doc["misc"]["zindex"].values()
                       if isinstance(t, dict) and "$value" in t} | set(cfg.get("zIndexLadder", []))
        self.old_names = [(o, n) for o, n in rmap["pairs"] if not o.startswith("#")]
        self.old_ids = [(o.lstrip("#"), n) for o, n in rmap["pairs"] if o.startswith("#")]
        self.known_classes = _class_index(root)
        self.allow_colors = {c.lower() for c in cfg.get("allowColors", [])}
        self.allow_token_overrides = cfg.get("allowTokenOverrides", False)
        self.allow_radius = set(cfg.get("allowRadius", []))
        self.zindex_local = int(cfg.get("zIndexLocal", 5))
        # primitive -> semantic alias, for TDS012
        sem = doc["color"].get("semantic") or {}
        for alias in sem:
            if not alias.startswith("$"):
                self.token_names.add(alias)
        self.alias_of = {}
        for alias, tok in sem.items():
            if alias.startswith("$") or not isinstance(tok, dict):
                continue
            prim = str(tok["$value"]).strip("{}").split(".")[-1]
            if prim != alias:
                self.alias_of.setdefault(prim, alias)
        self.contrast_pairs = cfg.get("contrastPairs", [
            ["text-primary", "surface-page", "text"],
            ["text-primary", "surface-card", "text"],
            ["text-secondary", "surface-page", "text"],
            ["text-secondary", "surface-card", "text"],
            ["interactive", "surface-page", "text"],
            ["interactive", "surface-card", "text"],
            ["text-placeholder", "surface-card", "text"],
            ["text-soft", "surface-card", "text"],
            ["status-success", "surface-card", "text"],
            ["status-warning", "surface-card", "text"],
            ["status-danger", "surface-card", "text"],
            ["status-success", "status-success-bg", "text"],
            ["status-warning", "status-warning-bg", "text"],
            ["status-danger", "status-danger-bg", "text"],
            ["interactive", "interactive-subtle", "text"],
            ["text-on-ink", "interactive-solid", "text"],
            ["text-on-ink", "status-success-solid", "text"],
            ["text-on-ink", "status-warning-solid", "text"],
            ["text-on-ink", "status-danger-solid", "text"],
            ["text-on-ink", "ink-panel", "text"],
            ["text-primary", "surface-banner", "text"],
            ["text-on-ink", "surface-banner-ink", "text"],
            ["text-ink-soft", "ink-hover", "text"],
            ["ink-secondary", "ink-panel", "text"],
            ["control-border", "surface-card", "nontext"],
        ])
        self.config = cfg

    def severity(self, rule_id):
        override = (self.config.get("rules") or {}).get(rule_id)
        if override == "off":
            return None
        if override in SEVERITIES:
            return override
        return self.rules[rule_id]["severity"]

    def fix(self, rule_id):
        return self.rules[rule_id]["fix"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _norm_hex(value):
    return value.lower()


def _class_index(root):
    names = set()
    for fn in ("base.css", "patterns.css"):
        path = os.path.join(root, "core", fn)
        if not os.path.exists(path):
            continue
        text = open(path).read()
        for m in re.finditer(r"\.([A-Za-z][\w-]*)", text):
            names.add(m.group(1))
    return names


def _blank_comments(text, pattern):
    return re.sub(pattern, lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)


def strip_css_comments(text):
    return _blank_comments(text, r"/\*.*?\*/")


def strip_html_comments(text):
    return _blank_comments(text, r"<!--.*?-->")


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
_RGB_RE = re.compile(r"\brgba?\([^)]*\)")
_MODERN_RE = re.compile(r"\b(?:hsla?|hwb|lab|lch|oklab|oklch|color|color-mix)\([^)]*\)")
_NAMED_RE = re.compile(
    r"(?<![\w-])(white|black|red|green|blue|yellow|orange|purple|pink|brown|gray|grey|teal|navy|"
    r"maroon|olive|lime|aqua|fuchsia|silver|gold|indigo|violet|cyan|magenta|coral|salmon|khaki|"
    r"crimson)(?![\w-])", re.I)


def _colour_matches(text):
    """hex, rgb(a), modern syntaxes and named colours, in position order."""
    out = []
    for rx in (_HEX_RE, _RGB_RE, _MODERN_RE, _NAMED_RE):
        out.extend(rx.finditer(text))
    return sorted(out, key=lambda m: m.start())
_DUR_RE = re.compile(r"(\d*\.?\d+)\s*(ms|s)\b")
_PX_RE = re.compile(r"(-?\d+(?:\.\d+)?)px")
_SPACING_PROPS = re.compile(r"^(margin|padding|gap|row-gap|column-gap|inset)(-(top|right|bottom|left|block|inline|start|end|[a-z]+))?$")
_STYLE_ATTR_RE = re.compile(r"""\bstyle\s*=\s*(["'])(.*?)\1""", re.S)
_CLASS_ATTR_RE = re.compile(r"""\b(?:class|className)\s*=\s*(["'])(.*?)\1""", re.S)
_TEMPLATE_CLASS_RE = re.compile(r"""className\s*=\s*\{([^}]*)\}""")
_ID_ATTR_RE = re.compile(r"""\bid\s*=\s*(["'])([^"']+)\1""")
_JS_CLASS_ADD_RE = re.compile(r"""classList\.(?:add|remove|toggle)\(\s*['"]([A-Za-z][\w-]*)['"]""")
_JS_SELECTOR_RE = re.compile(r"""(?:querySelector|querySelectorAll|getElementById)\(\s*['"]([.#]?[A-Za-z][\w-]*)['"]""")
_JS_STYLE_RE = re.compile(r"""\b(borderRadius|zIndex|color|background|backgroundColor)\s*:\s*(['"][^'"]+['"]|-?\d+[a-z%]*)""")


class _Suppressions(object):
    def __init__(self, text, path):
        self.path = path
        self.file_off = bool(re.search(r"triage-disable-file", text))
        self.lines = {}
        for i, line in enumerate(text.split("\n"), 1):
            m = re.search(r"triage-allow\s+(TDS\d+(?:\s*,\s*TDS\d+)*)", line)
            if m:
                ids = [x.strip() for x in m.group(1).split(",")]
                self.lines[i] = self.lines.get(i, []) + ids
                self.lines[i + 1] = self.lines.get(i + 1, []) + ids

    def allows(self, rule, line):
        return self.file_off or rule in self.lines.get(line, [])


# ---------------------------------------------------------------------------
# CSS parsing
# ---------------------------------------------------------------------------

def _find_matching(css, open_pos):
    depth = 1
    i = open_pos + 1
    while i < len(css) and depth:
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
        i += 1
    return i - 1


def _has_top_level_brace(inner):
    depth = 0
    for ch in inner:
        if ch == "{":
            if depth == 0:
                return True
            depth += 1
        elif ch == "}":
            depth -= 1
    return False


def iter_rules(css, start=0, end=None):
    """Yield (selector, body, body_start_pos) for leaf declaration blocks."""
    end = len(css) if end is None else end
    i = start
    sel_start = start
    while i < end:
        c = css[i]
        if c == "{":
            close = _find_matching(css, i)
            if close < 0:
                return
            selector = css[sel_start:i].strip()
            inner = css[i + 1:close]
            if _has_top_level_brace(inner):
                for item in iter_rules(css, i + 1, close):
                    yield item
            else:
                yield selector, inner, i + 1
            i = close + 1
            sel_start = i
            continue
        if c in ";}":
            sel_start = i + 1
        i += 1


def _declarations(body, base_pos):
    """Yield (prop, value, absolute_pos)."""
    pos = 0
    for part in body.split(";"):
        at = body.find(part, pos)
        pos = at + len(part) + 1
        if ":" in part:
            prop, _, val = part.partition(":")
            yield prop.strip().lower(), val.strip(), base_pos + at


# ---------------------------------------------------------------------------
# CSS scanner
# ---------------------------------------------------------------------------

# TDS016 — label-role classes whose tier the comfortable-density target covers.
LABEL_ROLES = ("badge", "nav-label", "cmd-group")


def scan_css(path, text, spec, base_line=1, suppressions=None):
    findings = []
    css = strip_css_comments(text)
    sup = suppressions or _Suppressions(text, path)

    def add(rule, pos, message, excerpt, force=None):
        base = spec.severity(rule)
        if base is None or sup.allows(rule, line_of(css, pos)):
            return
        findings.append(Finding(rule, force or base, path, line_of(css, pos), message, excerpt, spec.fix(rule)))

    for selector, body, bpos in iter_rules(css):
        for old, new in spec.old_names:
            if re.search(r"\." + re.escape(old) + r"(?![\w-])", selector):
                add("TDS001", bpos, "deprecated class .%s — use .%s" % (old, new.lstrip(".")), selector)
        for old, new in spec.old_ids:
            if re.search(r"#" + re.escape(old) + r"(?![\w-])", selector):
                add("TDS001", bpos, "deprecated id #%s — use %s" % (old, new), selector)
        for prop, val, pos in _declarations(body, bpos):
            excerpt = "%s: %s" % (prop, val)
            if prop.startswith("--") and path.endswith("tokens.css"):
                continue   # the token definition file itself
            for m in _colour_matches(val):
                raw = m.group(0)
                in_palette = raw.startswith("#") and _norm_hex(raw) in spec.token_values
                if raw.lower() in spec.allow_colors:
                    continue
                if in_palette:
                    add("TDS002", pos + m.start(),
                        "palette colour %s used raw — use var(--%s)" % (raw, spec.token_values[_norm_hex(raw)]),
                        excerpt, force="error")
                else:
                    add("TDS002", pos + m.start(), "off-system colour %s" % raw, excerpt)
            if prop.endswith("radius"):
                base = re.sub(r"\s*!important\s*$", "", val).strip()
                if base not in (spec.allow_radius | {"0", "0px", "inherit", "initial", "unset"}):
                    add("TDS003", pos, "non-zero border-radius %s" % val, excerpt)
            if prop == "outline" and re.fullmatch(r"(none|0(px)?)", val):
                replaced = (":focus-visible" in selector or
                            re.search(r"box-shadow|border-color", body))
                if not replaced:
                    add("TDS004", pos, "outline removed with no visible focus replacement", excerpt)
            if _SPACING_PROPS.match(prop) and "calc(" not in val and "var(" not in val:
                for m in _PX_RE.finditer(val):
                    v = abs(float(m.group(1)))
                    if v != int(v) or int(v) not in spec.spacing:
                        add("TDS005", pos + m.start(), "spacing %s outside the scale" % m.group(0), excerpt)
            if prop.startswith("transition") or prop.startswith("animation"):
                for m in _DUR_RE.finditer(val):
                    ms = float(m.group(1)) * (1000 if m.group(2) == "s" else 1)
                    if ms > 1 and int(ms) not in spec.durations:
                        add("TDS006", pos + m.start(), "duration %s not a motion token" % m.group(0), excerpt)
            if prop == "z-index" and re.fullmatch(r"-?\d+", val):
                z = int(val)
                if z > spec.zindex_local and z not in spec.zindex:
                    add("TDS007", pos, "z-index %s outside the ladder" % val, excerpt)
            if prop == "font-family" and not re.search(r"geist|var\(--(mono|font-mono|font-sans)\)|inherit", val, re.I):
                add("TDS008", pos, "off-system font stack %s" % val, excerpt)
            if (prop.startswith("--") and prop[2:] in spec.token_names
                    and not spec.allow_token_overrides
                    and not path.endswith("tokens.css")):
                add("TDS009", pos, "redefines system token --%s" % prop[2:], excerpt)
        # TDS016 — label tier (info): label-role classes below the comfortable target
        for cls in LABEL_ROLES:
            if not re.search(r"\." + re.escape(cls) + r"(?![\w-])", selector):
                continue
            for prop, val, pos in _declarations(body, bpos):
                if prop == "font-size":
                    m = re.match(r"^([\d.]+)(px|rem)$", val)
                    if m and ((m.group(2) == "px" and float(m.group(1)) < 13)
                              or (m.group(2) == "rem" and float(m.group(1)) < 0.8125)):
                        add("TDS016", pos,
                            "label-role .%s below the comfortable label target "
                            "(13px at the 16px root)" % cls,
                            "font-size: %s" % val)
            break
    return findings


# ---------------------------------------------------------------------------
# markup / JS scanners
# ---------------------------------------------------------------------------

def _check_classes(tokens, spec, path, line, excerpt, findings, sup, check_unknown):
    for cls in tokens.split():
        for old, new in spec.old_names:
            if cls == old or cls.startswith(old + "-"):
                sev = spec.severity("TDS001")
                if sev and not sup.allows("TDS001", line):
                    findings.append(Finding("TDS001", sev, path, line,
                                            "deprecated class %s — use %s" % (cls, new), excerpt,
                                            spec.fix("TDS001")))
        if check_unknown and not cls.startswith("p-") and cls not in spec.known_classes:
            sev = spec.severity("TDS010")
            if sev and not sup.allows("TDS010", line):
                findings.append(Finding("TDS010", sev, path, line,
                                        "class .%s is not in core.css / patterns.css" % cls, excerpt,
                                        spec.fix("TDS010")))


def _style_decl(path, line, prop, val, spec, findings, sup):
    def add(rule, message, excerpt, force=None):
        base = spec.severity(rule)
        if base is None or sup.allows(rule, line):
            return
        findings.append(Finding(rule, force or base, path, line, message, excerpt, spec.fix(rule)))

    excerpt = "%s: %s" % (prop, val)
    for m in _colour_matches(val):
        raw = m.group(0)
        in_palette = raw.startswith("#") and _norm_hex(raw) in spec.token_values
        if raw.lower() in spec.allow_colors:
            continue
        if in_palette:
            add("TDS002", "palette colour %s used raw — use var(--%s)" % (raw, spec.token_values[_norm_hex(raw)]),
                excerpt, force="error")
        else:
            add("TDS002", "off-system colour %s" % raw, excerpt)
    if prop.endswith("radius"):
        base = re.sub(r"\s*!important\s*$", "", val).strip()
        if base not in (spec.allow_radius | {"0", "0px", "inherit", "initial", "unset"}):
            add("TDS003", "non-zero border-radius %s" % val, excerpt)
    if _SPACING_PROPS.match(prop) and "calc(" not in val and "var(" not in val:
        for m in _PX_RE.finditer(val):
            v = abs(float(m.group(1)))
            if v != int(v) or int(v) not in spec.spacing:
                add("TDS005", "spacing %s outside the scale" % m.group(0), excerpt)
    if prop in ("z-index", "zIndex") and re.fullmatch(r"-?\d+", val):
        z = int(val)
        if z > spec.zindex_local and z not in spec.zindex:
            add("TDS007", "z-index %s outside the ladder" % val, excerpt)


def scan_markup(path, text, spec, suppressions=None, check_unknown=False):
    findings = []
    sup = suppressions or _Suppressions(text, path)
    clean = strip_html_comments(text)

    for m in _CLASS_ATTR_RE.finditer(clean):
        _check_classes(m.group(2), spec, path, line_of(clean, m.start()), m.group(0)[:120],
                       findings, sup, check_unknown)
    for m in _TEMPLATE_CLASS_RE.finditer(clean):
        inner = " ".join(re.findall(r"['\"]([^'\"]+)['\"]", m.group(1)))
        _check_classes(inner, spec, path, line_of(clean, m.start()), m.group(0)[:120],
                       findings, sup, check_unknown)
    for m in _ID_ATTR_RE.finditer(clean):
        _check_classes(m.group(2), spec, path, line_of(clean, m.start()), m.group(0)[:120],
                       findings, sup, False)
    for m in _STYLE_ATTR_RE.finditer(clean):
        line = line_of(clean, m.start())
        for prop, val, _pos in _declarations(m.group(2), 0):
            _style_decl(path, line, prop, val, spec, findings, sup)
    # TDS014 / TDS015 — accessibility basics
    for m in re.finditer(r"<img\b[^>]*>", clean, re.I):
        if not re.search(r"\balt\s*=", m.group(0), re.I):
            line = line_of(clean, m.start())
            sev = spec.severity("TDS014")
            if sev and not sup.allows("TDS014", line):
                findings.append(Finding("TDS014", sev, path, line,
                    "<img> without alt", m.group(0)[:100], spec.fix("TDS014")))
    for m in re.finditer(r"<(button|a)\b[^>]*>(.*?)</\1>", clean, re.I | re.S):
        attr, inner = m.group(0), m.group(2)
        text = re.sub(r"<[^>]*>", "", inner).strip()
        if text or re.search(r"aria-label|title=", attr, re.I):
            continue
        line = line_of(clean, m.start())
        sev = spec.severity("TDS015")
        if sev and not sup.allows("TDS015", line):
            findings.append(Finding("TDS015", sev, path, line,
                "<%s> has no accessible name" % m.group(1).lower(), attr[:100], spec.fix("TDS015")))
    for m in re.finditer(r"tabindex\s*=\s*[\"']([1-9]\d*)", clean):
        line = line_of(clean, m.start())
        sev = spec.severity("TDS015")
        if sev and not sup.allows("TDS015", line):
            findings.append(Finding("TDS015", "warning", path, line,
                "positive tabindex=%s breaks natural order" % m.group(1), m.group(0)[:100], spec.fix("TDS015")))
    for m in re.finditer(r"<style[^>]*>(.*?)</style>", clean, re.S):
        findings.extend(scan_css(path, m.group(1), spec,
                                 base_line=line_of(clean, m.start(1)), suppressions=sup))
    return findings


def scan_js(path, text, spec, suppressions=None, check_unknown=False):
    findings = []
    sup = suppressions or _Suppressions(text, path)

    def add(rule, line, message, excerpt, force=None):
        base = spec.severity(rule)
        if base is None or sup.allows(rule, line):
            return
        findings.append(Finding(rule, force or base, path, line, message, excerpt, spec.fix(rule)))

    for m in _JS_CLASS_ADD_RE.finditer(text):
        name = m.group(1)
        for old, new in spec.old_names:
            if name == old:
                add("TDS001", line_of(text, m.start()),
                    "deprecated class %s — use %s" % (name, new), m.group(0)[:100])
    for m in _JS_SELECTOR_RE.finditer(text):
        name = m.group(1).lstrip(".#")
        for old, new in spec.old_names:
            if name == old:
                add("TDS001", line_of(text, m.start()),
                    "deprecated selector %s — use %s" % (m.group(1), new), m.group(0)[:100])
    for m in _JS_STYLE_RE.finditer(text):
        key, val = m.group(1), m.group(2)
        line = line_of(text, m.start())
        raw = val.strip("'\"")
        if key == "borderRadius" and not re.fullmatch(r"0(px)?", raw):
            add("TDS003", line, "non-zero borderRadius %s" % raw, m.group(0)[:100])
        if key == "zIndex" and re.fullmatch(r"\d+", raw) and int(raw) != 0 and int(raw) not in spec.zindex:
            add("TDS007", line, "z-index %s outside the ladder" % raw, m.group(0)[:100])
        if key in ("color", "background", "backgroundColor"):
            for cm in _colour_matches(raw):
                c = cm.group(0)
                norm = _norm_hex(c) if c.startswith("#") else None
                if norm and norm in spec.token_values:
                    add("TDS002", line, "palette colour %s used raw — use var(--%s)"
                        % (c, spec.token_values[norm]), m.group(0)[:100], force="error")
                else:
                    add("TDS002", line, "off-system colour %s" % c, m.group(0)[:100])
    for m in re.finditer(r"""['"]([^'"]*#[0-9a-fA-F]{3,8}[^'"]*)['"]""", text):
        line = line_of(text, m.start())
        for c in _HEX_RE.findall(m.group(1)):
            token = spec.token_values.get(_norm_hex(c))
            if token:
                add("TDS002", line, "palette colour %s in a string — use var(--%s)" % (c, token), m.group(0)[:100])
            else:
                add("TDS002", line, "off-system colour %s in a string" % c, m.group(0)[:100])
    return findings




# ---------------------------------------------------------------------------
# cross-cutting rules: TDS011 contrast, TDS012 alias preference, TDS013 logical
# ---------------------------------------------------------------------------

_NAMED_RGB = {"white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0),
              "green": (0, 128, 0), "blue": (0, 0, 255), "gray": (128, 128, 128),
              "grey": (128, 128, 128), "silver": (192, 192, 192), "orange": (255, 165, 0)}


def _hsl_to_rgb(h, s, l):
    h = (h % 360) / 360.0
    s = max(0.0, min(1.0, s))
    l = max(0.0, min(1.0, l))
    if s == 0:
        r = g = b = l
    else:
        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        def f(t):
            if t < 0: t += 1
            if t > 1: t -= 1
            if t < 1 / 6: return p + (q - p) * 6 * t
            if t < 1 / 2: return q
            if t < 2 / 3: return p + (q - p) * (2 / 3 - t) * 6
            return p
        r, g, b = f(h + 1 / 3), f(h), f(h - 1 / 3)
    return r * 255, g * 255, b * 255


def _lum(value):
    v = value.strip().lower()
    if v in _NAMED_RGB:
        r, g, b = _NAMED_RGB[v]
    elif v.startswith("rgb"):
        nums = re.findall(r"[-\d.]+%?", v[v.index("(") + 1:v.rindex(")")])
        if len(nums) < 3:
            return None
        r, g, b = [(float(n[:-1]) * 2.55 if n.endswith("%") else float(n)) for n in nums[:3]]
    elif v.startswith("hsl"):
        nums = re.findall(r"[-\d.]+", v[v.index("(") + 1:v.rindex(")")])
        if len(nums) < 3:
            return None
        r, g, b = _hsl_to_rgb(float(nums[0]), float(nums[1]) / 100.0, float(nums[2]) / 100.0)
    elif v.startswith("#"):
        h = v.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 8:
            h = h[:6]
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    else:
        return None
    def ch(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    if la is None or lb is None:
        return None
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _defined_tokens(css):
    """Definitions per theme. Returns (light, dark) property maps with var() chains resolved.

    Light: first definition of each property before any dark-theme block.
    Dark: light map overlaid with every definition inside a dark block.
    """
    css = strip_css_comments(css)
    dark_markers = [m.start() for m in re.finditer(r"prefers-color-scheme:\s*dark|data-theme=\\?\"dark", css)]
    dark_start = min(dark_markers) if dark_markers else len(css)
    light, dark = {}, {}
    for m in re.finditer(r"--([\w-]+)\s*:\s*([^;{}]+)", css):
        name, val = m.group(1), m.group(2).strip()
        if m.start() < dark_start:
            light.setdefault(name, val)
        else:
            dark[name] = val

    def resolve(raw, name, depth=0):
        if depth > 6 or name not in raw:
            return None
        val = raw[name]
        if not isinstance(val, str):
            return None
        vm = re.match(r"var\(--([\w-]+)\)", val)
        return resolve(raw, vm.group(1), depth + 1) if vm else val

    light = {k: resolve(light, k) for k in light}
    merged = dict(light)
    merged.update(dark)
    merged = {k: resolve(merged, k) for k in merged}
    return light, merged


def _cross_checks(path, text, spec, sup):
    findings = []
    ext = os.path.splitext(path)[1].lower()
    clean = strip_css_comments(text) if ext == ".css" else text

    # TDS011 — contrast audit of defined tokens (CSS only, and only if the file defines them)
    if ext == ".css":
        light_map, dark_map = _defined_tokens(clean)
        sev = spec.severity("TDS011")
        for theme, defined in (("light", light_map), ("dark", dark_map)):
            resolved = [(f, b, k) for f, b, k in spec.contrast_pairs if f in defined and b in defined]
            if sev is None or len(resolved) < 3:
                break
            for fg, bg, kind in resolved:
                ratio = _contrast(defined[fg], defined[bg])
                need = 4.5 if kind == "text" else 3.0
                if ratio is not None and ratio < need and not sup.allows("TDS011", 1):
                    line = next((line_of(clean, m.start()) for m in re.finditer(r"--%s\s*:" % re.escape(fg), clean)), 1)
                    findings.append(Finding("TDS011", sev, path, line,
                        "[%s] --%s on --%s is %.2f:1 (needs %s:1)" % (theme, fg, bg, ratio, need),
                        "%s / %s" % (defined[fg], defined[bg]), spec.fix("TDS011")))

    # TDS012 — prefer semantic aliases over primitives
    sev12 = spec.severity("TDS012")
    if sev12:
        for m in re.finditer(r"var\(--([\w-]+)\)", clean):
            prim = m.group(1)
            if prim not in spec.alias_of:
                continue
            line = line_of(clean, m.start())
            line_text = clean.split("\n")[line - 1]
            seg_start = max(clean.rfind("{", 0, m.start()), clean.rfind(";", 0, m.start()), clean.rfind("}", 0, m.start())) + 1
            if re.match(r"\s*--[\w-]+\s*:", clean[seg_start:m.start()]):   # alias/token definition itself
                continue
            if sup.allows("TDS012", line):
                continue
            findings.append(Finding("TDS012", sev12, path, line,
                "prefer var(--%s) over primitive var(--%s)" % (spec.alias_of[prim], prim),
                line_text.strip()[:100], spec.fix("TDS012")))

    # TDS012b — local variable built from a primitive
    if sev12 and not path.endswith("tokens.css"):
        for m in re.finditer(r"--([\w-]+)\s*:\s*var\(--([\w-]+)\)", clean):
            alias = spec.alias_of.get(m.group(2))
            if not alias:
                continue
            line = line_of(clean, m.start())
            if sup.allows("TDS012", line):
                continue
            findings.append(Finding("TDS012", sev12, path, line,
                "local --%s is built from primitive var(--%s); use var(--%s)" % (m.group(1), m.group(2), alias),
                clean.split("\n")[line - 1].strip()[:100], spec.fix("TDS012")))

    # TDS013 — physical direction properties
    sev13 = spec.severity("TDS013")
    if sev13:
        phys = re.compile(r"(?<![\w-])(margin|padding|border)-(left|right)(-width|-color)?\s*:|(?<![\w-])(left|right)\s*:\s*[^;]+|text-align\s*:\s*(left|right)\b|float\s*:\s*(left|right)\b")
        for m in phys.finditer(clean):
            line = line_of(clean, m.start())
            if sup.allows("TDS013", line):
                continue
            findings.append(Finding("TDS013", sev13, path, line,
                "physical direction property — use logical properties (inline-start/end)",
                clean.split("\n")[line - 1].strip()[:100], spec.fix("TDS013")))
    return findings


SCANNERS = {
    ".css": scan_css,
    ".html": scan_markup,
    ".htm": scan_markup,
    ".vue": scan_markup,
    ".svelte": scan_markup,
    ".jsx": scan_markup,
    ".tsx": scan_markup,
    ".js": scan_js,
    ".mjs": scan_js,
    ".ts": scan_js,
    ".py": scan_markup,
}


def scan_text(path, text, spec, check_unknown=False):
    ext = os.path.splitext(path)[1].lower()
    sup = _Suppressions(text, path)
    if ext in (".css", ".scss", ".less"):
        out = scan_css(path, text, spec, suppressions=sup)
    elif ext in (".html", ".htm", ".vue", ".svelte", ".jsx", ".tsx", ".py", ".astro", ".mdx"):
        out = scan_markup(path, text, spec, suppressions=sup, check_unknown=check_unknown)
    elif ext in (".js", ".mjs", ".ts"):
        out = scan_js(path, text, spec, suppressions=sup)
    else:
        return []
    out.extend(_cross_checks(path, text, spec, sup))
    return out
