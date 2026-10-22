"""Unit tests for the Triage lint engine (stdlib unittest)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "lint"))

from engine import Spec, scan_text  # noqa: E402


def rules(text, ext=".css", config=None, check_unknown=False):
    spec = Spec(ROOT, config or {})
    return [f.rule for f in scan_text("t.css" if ext == ".css" else "t" + ext, text, spec, check_unknown)]


class TestColour(unittest.TestCase):
    def test_palette_raw_is_error(self):
        spec = Spec(ROOT, {})
        out = scan_text("t.css", ".a{color:#fafafa}", spec)
        self.assertEqual(out[0].rule, "TDS002")
        self.assertEqual(out[0].severity, "error")
        self.assertIn("--bg", out[0].message)

    def test_off_system_is_warning(self):
        spec = Spec(ROOT, {})
        out = scan_text("t.css", ".a{color:#123456}", spec)
        self.assertEqual(out[0].severity, "warning")

    def test_allowed_colour(self):
        spec = Spec(ROOT, {"allowColors": ["#123456"]})
        self.assertEqual(scan_text("t.css", ".a{color:#123456}", spec), [])

    def test_rule_off(self):
        spec = Spec(ROOT, {"rules": {"TDS002": "off"}})
        self.assertEqual(scan_text("t.css", ".a{color:#fafafa}", spec), [])

    def test_severity_override(self):
        spec = Spec(ROOT, {"rules": {"TDS002": "info"}})
        self.assertEqual(scan_text("t.css", ".a{color:#123456}", spec)[0].severity, "info")

    def test_inline_style_attr(self):
        spec = Spec(ROOT, {})
        out = scan_text("t.html", '<div style="color:#fafafa"></div>', spec)
        self.assertEqual([f.rule for f in out], ["TDS002"])


class TestStructure(unittest.TestCase):
    def test_radius(self):
        self.assertIn("TDS003", rules(".a{border-radius:4px}"))
        self.assertEqual(rules(".a{border-radius:0}"), [])
        self.assertEqual(rules(".a{border-radius:0px}"), [])

    def test_focus_removal(self):
        self.assertIn("TDS004", rules(".a:focus{outline:none}"))
        self.assertEqual(rules(".a:focus-visible{outline:none;box-shadow:0 0 0 2px var(--interactive)}"), [])
        # replacement in the same block counts
        self.assertEqual(rules(".a:focus{outline:none;border-color:var(--text-primary)}"), [])

    def test_spacing(self):
        self.assertIn("TDS005", rules(".a{padding:37px}"))
        self.assertEqual(rules(".a{padding:12px}"), [])
        self.assertEqual(rules(".a{margin:0 8px 16px 24px}"), [])
        self.assertEqual(rules(".a{bottom:calc(72px + env(safe-area-inset-bottom))}"), [])

    def test_motion(self):
        self.assertIn("TDS006", rules(".a{transition:opacity .33s ease}"))
        self.assertEqual(rules(".a{transition:opacity .18s ease}"), [])

    def test_zindex(self):
        self.assertIn("TDS007", rules(".a{z-index:9999}"))
        self.assertEqual(rules(".a{z-index:300}"), [])

    def test_font(self):
        self.assertIn("TDS008", rules(".a{font-family:Arial}"))
        self.assertEqual(rules(".a{font-family:'Geist',sans-serif}"), [])

    def test_token_override(self):
        self.assertIn("TDS009", rules(":root{--bg:#fff}"))
        self.assertEqual(rules(".x{--local-gap:4px}"), [])


class TestNames(unittest.TestCase):
    def test_deprecated_class_markup(self):
        out = rules('<div class="msgrid"></div>', ".html")
        self.assertIn("TDS001", out)

    def test_deprecated_class_css(self):
        self.assertIn("TDS001", rules(".mfeed .mrow{padding:4px}"))

    def test_deprecated_js(self):
        out = rules("el.classList.add('mfeed')", ".js")
        self.assertIn("TDS001", out)

    def test_current_class_is_clean(self):
        self.assertEqual(rules(".detail-grid .feed-row{padding:4px}"), [])

    def test_unknown_class_opt_in(self):
        self.assertEqual(rules('<div class="my-chart"></div>', ".html"), [])
        self.assertIn("TDS010", rules('<div class="my-chart"></div>', ".html", check_unknown=True))


class TestSuppression(unittest.TestCase):
    def test_allow_line(self):
        text = "/* triage-allow TDS003 */\n.a{border-radius:4px}"
        self.assertEqual(rules(text), [])

    def test_disable_file(self):
        self.assertEqual(rules("/* triage-disable-file */\n.a{border-radius:4px}"), [])


class TestHardening(unittest.TestCase):
    def test_named_colour_flagged(self):
        self.assertIn("TDS002", rules(".a{color:red}"))

    def test_modern_colour_flagged(self):
        self.assertIn("TDS002", rules(".a{color:oklch(.6 .2 30)}"))
        self.assertIn("TDS002", rules(".a{color:hsl(210 100% 50%)}"))

    def test_space_rgb_contrast_no_crash(self):
        css = ":root{--text-primary:rgb(0 0 0);--surface-page:#ffffff;--surface-card:#fff;--text-secondary:#666666;--interactive:#0068e0}"
        rules(css)  # must not raise

    def test_alias_override_caught(self):
        self.assertIn("TDS009", rules(":root{--surface-page:red}"))

    def test_outline_bypass_caught(self):
        self.assertIn("TDS004", rules(".a:focus{outline:none;background:white}"))
        self.assertEqual(rules(".a:focus{outline:none;border-color:var(--text-primary)}"), [])

    def test_radius_50_now_flagged(self):
        self.assertIn("TDS003", rules(".r{border-radius:50%}"))

    def test_js_hex_string_no_crash(self):
        rules("const x = '#abcdef';", ".js")

    def test_local_var_from_primitive(self):
        self.assertIn("TDS012", rules(".x{--brand:var(--acc)}"))


class TestNewRules(unittest.TestCase):
    def test_contrast_rule(self):
        css = ":root{--text-primary:#aaaaaa;--surface-page:#ffffff;--surface-card:#fff;--text-secondary:#eee;--interactive:#ccc}"
        self.assertIn("TDS011", rules(css))

    def test_contrast_dark_theme_checked(self):
        css = (":root{--text-primary:#000000;--surface-page:#ffffff;--surface-card:#ffffff;"
               "--text-secondary:#666666;--interactive:#0068e0}\n"
               "@media (prefers-color-scheme: dark){:root:not([data-theme=\"light\"]){--text-primary:#666666;--surface-page:#0f0f0f}}")
        out = scan_text("t.css", css, Spec(ROOT, {}))
        self.assertTrue(any(f.rule == "TDS011" and "dark" in f.message for f in out))

    def test_contrast_pass(self):
        css = ":root{--text-primary:#000000;--surface-page:#fafafa;--surface-card:#ffffff;--text-secondary:#666666;--interactive:#0068e0}"
        self.assertNotIn("TDS011", rules(css))

    def test_alias_preference(self):
        out = [f for f in scan_text("t.css", ".a{color:var(--fg)}", Spec(ROOT, {}))]
        self.assertEqual(out[0].rule, "TDS012")

    def test_definition_line_exempt(self):
        out = rules(":root{--brand-gap:4px}")
        self.assertNotIn("TDS012", out)

    def test_logical_direction(self):
        self.assertIn("TDS013", rules(".a{margin-left:4px}"))
        self.assertIn("TDS013", rules(".a{text-align:right}"))
        self.assertEqual(rules(".a{margin-inline-start:4px}"), [])


class TestA11yRules(unittest.TestCase):
    def test_img_alt(self):
        self.assertIn("TDS014", rules('<img src="x.png">', ".html"))
        self.assertEqual(rules('<img src="x.png" alt="">', ".html"), [])

    def test_empty_button(self):
        self.assertIn("TDS015", rules('<button class="iconbtn"></button>', ".html"))
        self.assertEqual(rules('<button aria-label="Close"></button>', ".html"), [])
        self.assertEqual(rules('<button><svg></svg>Close</button>', ".html"), [])

    def test_positive_tabindex(self):
        self.assertIn("TDS015", rules('<div tabindex="3"></div>', ".html"))
        self.assertEqual(rules('<div tabindex="0"></div>', ".html"), [])


class TestLabelTier(unittest.TestCase):
    def test_below_target_is_info(self):
        spec = Spec(ROOT, {})
        out = scan_text("t.css", ".badge{font-size:11px}", spec)
        self.assertEqual(out[0].rule, "TDS016")
        self.assertEqual(out[0].severity, "info")

    def test_rem_below_target(self):
        spec = Spec(ROOT, {})
        out = scan_text("t.css", ".nav-label{font-size:0.75rem}", spec)
        self.assertEqual([f.rule for f in out], ["TDS016"])

    def test_at_target_is_clean(self):
        self.assertEqual(rules(".badge{font-size:13px}"), [])
        self.assertEqual(rules(".nav-label{font-size:0.8125rem}"), [])
        self.assertEqual(rules(".cmd-group{font-size:14px}"), [])

    def test_token_use_is_clean(self):
        self.assertEqual(rules(".badge{font-size:var(--fs-badge)}"), [])

    def test_non_label_class_is_clean(self):
        self.assertEqual(rules(".log-row{font-size:12px}"), [])
        self.assertEqual(rules(".kbd{font-size:0.75rem}"), [])

    def test_rule_off(self):
        spec = Spec(ROOT, {"rules": {"TDS016": "off"}})
        self.assertEqual(scan_text("t.css", ".badge{font-size:11px}", spec), [])


class TestScore(unittest.TestCase):
    def test_score_formula(self):
        from triage_lint import severity_score
        self.assertEqual(severity_score({"error": 1, "warning": 0, "info": 0}), 92)
        self.assertEqual(severity_score({"error": 0, "warning": 1, "info": 0}), 98)
        self.assertEqual(severity_score({"error": 0, "warning": 0, "info": 2}), 99)
        self.assertEqual(severity_score({"error": 20, "warning": 0, "info": 0}), 0)


if __name__ == "__main__":
    unittest.main()
