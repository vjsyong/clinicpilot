"""Mutation tests for the token pipeline (stdlib unittest).

These are the "changing a token changes its generated output" acceptance
evidence: each test deep-copies the token document (or breakpoint map), mutates
one foundation token, and asserts the generated output follows. They are
discovered by the standard `python3 -m unittest discover -s lint/tests -t .`.
"""
import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def _load_module(name, relpath):
    path = os.path.join(ROOT, relpath)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_tokens = _load_module("tds_build_tokens", os.path.join("tools", "build_tokens.py"))
build_core = _load_module("tds_build_core", os.path.join("tools", "build_core.py"))
token_map = _load_module("tds_token_map", os.path.join("tools", "token_map.py"))


def _doc():
    with open(os.path.join(ROOT, "tokens", "tokens.json")) as fh:
        return json.load(fh)


class TestFontStacks(unittest.TestCase):
    def test_family_text_drives_font_sans(self):
        doc = _doc()
        before = build_tokens.render_css(doc)
        doc["typography"]["family-text"]["$value"] = ["Test Sans", "sans-serif"]
        after = build_tokens.render_css(doc)
        self.assertNotEqual(before, after)
        self.assertIn("--font-sans:'Test Sans', sans-serif;", after)
        self.assertNotIn("--font-sans:'Test Sans'", before)

    def test_family_mono_drives_font_mono_and_legacy_mono(self):
        doc = _doc()
        doc["typography"]["family-mono"]["$value"] = ["Test Mono", "monospace"]
        out = build_tokens.render_css(doc)
        self.assertIn("--font-mono:'Test Mono', monospace;", out)
        self.assertIn("--mono:'Test Mono', monospace;", out)

    def test_missing_family_is_a_clear_error(self):
        doc = _doc()
        del doc["typography"]["family-text"]
        with self.assertRaises(build_tokens.TokenError):
            build_tokens.render_css(doc)

    def test_empty_family_is_a_clear_error(self):
        with self.assertRaises(build_tokens.TokenError):
            build_tokens.font_stack([], "family-text")

    def test_bare_vs_quoted_family_names(self):
        # valid bare CSS identifiers stay bare; everything else is quoted/escaped
        self.assertEqual(build_tokens.font_stack(["42Berlin"], "k"), "'42Berlin'")
        self.assertEqual(build_tokens.font_stack(["-1foo"], "k"), "'-1foo'")
        self.assertEqual(build_tokens.font_stack(["O'Brien"], "k"), "'O\\'Brien'")
        self.assertEqual(build_tokens.font_stack(["Geist Mono"], "k"), "'Geist Mono'")
        self.assertEqual(build_tokens.font_stack(["sans-serif"], "k"), "sans-serif")
        self.assertEqual(build_tokens.font_stack(["Geist", "-apple-system"], "k"),
                         "Geist, -apple-system")
        self.assertEqual(build_tokens.font_stack(["monospace"], "k"), "monospace")


class TestBaseSize(unittest.TestCase):
    def test_base_size_drives_generated_rem_and_root_rule(self):
        doc = _doc()
        before = build_tokens.render_css(doc)
        self.assertIn("--base-size:1rem;", before)

        doc["typography"]["base-size"]["$value"]["value"] = 18
        after = build_tokens.render_css(doc)
        self.assertIn("--base-size:1.125rem;", after)
        self.assertNotEqual(before, after)

        # The composed root rule consumes the generated token, so the changed
        # value flows into the shipped stylesheet (the html rule itself keeps
        # referencing var(--base-size) rather than embedding a literal).
        composed = build_core.compose("core/base.css", ["additions.css"],
                                      build_core.load_breakpoints())
        self.assertIn("html{font-size:var(--base-size)}", composed)

    def test_non_numeric_base_size_is_a_clear_error(self):
        doc = _doc()
        doc["typography"]["base-size"]["$value"]["value"] = "big"
        with self.assertRaises(build_tokens.TokenError):
            build_tokens.render_css(doc)
        with self.assertRaises(build_tokens.TokenError):
            build_tokens._base_size("big")


class TestTypeScale(unittest.TestCase):
    def test_base_size_drives_the_design_scale(self):
        doc = _doc()
        before = build_tokens.render_css(doc)
        # at the shipped 16px base the authored px render at those px
        self.assertIn("--fs-body:1rem;", before)
        self.assertIn("--fs-h1:1.5rem;", before)
        self.assertIn("--fs-table:0.875rem;", before)

        # changing the base rescales every step (16/20 = 0.8rem, 24/20 = 1.2rem)
        doc["typography"]["base-size"]["$value"]["value"] = 20
        after = build_tokens.render_css(doc)
        self.assertIn("--base-size:1.25rem;", after)
        self.assertIn("--fs-body:0.8rem;", after)
        self.assertIn("--fs-h1:1.2rem;", after)
        self.assertNotEqual(before, after)

    def test_rem_divides_by_the_token_base(self):
        self.assertEqual(build_tokens._rem(16, 16), "1rem")
        self.assertEqual(build_tokens._rem(24, 16), "1.5rem")
        self.assertEqual(build_tokens._rem(12.5, 16), "0.7812rem")
        self.assertEqual(build_tokens._rem(16, 20), "0.8rem")

    def test_compact_extension_flows_into_generated_css(self):
        doc = _doc()
        before = build_tokens.render_css(doc)
        self.assertIn(':root[data-density="compact"]{', before)
        self.assertIn("--base-size:0.9375rem;--fs-log-row:0.8rem;", before)

        doc["typography"]["size-nav-label"]["$extensions"]["com.triage.compact"] = "0.85rem"
        after = build_tokens.render_css(doc)
        self.assertIn("--fs-nav-label:0.85rem;", after)
        self.assertNotIn("--fs-nav-label:0.85rem;", before)

    def test_compact_block_is_omitted_when_no_token_opts_in(self):
        doc = _doc()
        for tok in doc["typography"].values():
            if isinstance(tok, dict):
                (tok.get("$extensions") or {}).pop("com.triage.compact", None)
        out = build_tokens.render_css(doc)
        self.assertNotIn("data-density", out)


class TestBreakpoints(unittest.TestCase):
    def _write_doc(self, doc, tmp):
        path = os.path.join(tmp, "tokens.json")
        with open(path, "w") as fh:
            json.dump(doc, fh)
        return path

    def test_breakpoint_value_drives_composed_media_query(self):
        doc = _doc()
        with tempfile.TemporaryDirectory() as tmp:
            default = build_core.substitute("@media(max-width:{bp-md}){}",
                                            build_core.load_breakpoints(self._write_doc(doc, tmp)))
            self.assertEqual(default, "@media(max-width:900px){}")

            doc["misc"]["breakpoint"]["md"]["$value"]["value"] = 901
            mutated = build_core.substitute("@media(max-width:{bp-md}){}",
                                            build_core.load_breakpoints(self._write_doc(doc, tmp)))
            self.assertEqual(mutated, "@media(max-width:901px){}")

    def test_unknown_placeholder_fails(self):
        with self.assertRaises(build_core.CoreBuildError):
            build_core.substitute("@media(max-width:{bp-nope}){}", {"md": 900})

    def test_unresolved_placeholder_fails(self):
        with self.assertRaises(build_core.CoreBuildError):
            build_core.substitute("@media(max-width:{bp-md){}", {"md": 900})

    def test_compose_fails_on_unknown_placeholder_in_source(self):
        # the real additions.css carries {bp-sm}/{bp-lg}; an empty map must fail.
        with self.assertRaises(build_core.CoreBuildError):
            build_core.compose("core/base.css", ["additions.css"], {})

    def test_phone_up_is_derived_from_phone(self):
        doc = _doc()
        with tempfile.TemporaryDirectory() as tmp:
            # the shipped document is consistent and both tools accept it
            bp = build_core.load_breakpoints(self._write_doc(doc, tmp))
            self.assertEqual(bp["phone-up"], bp["phone"] + 1)
            out = build_tokens.render_css(doc)
            self.assertIn("--bp-phone:767px;", out)
            self.assertIn("--bp-phone-up:768px;", out)

            # moving phone without phone-up must fail both tools
            doc["misc"]["breakpoint"]["phone"]["$value"]["value"] = 700
            with self.assertRaises(build_core.CoreBuildError):
                build_core.load_breakpoints(self._write_doc(doc, tmp))
            with self.assertRaises(build_tokens.TokenError):
                build_tokens.render_css(doc)

            # moving both coherently is accepted and changes the output
            doc["misc"]["breakpoint"]["phone-up"]["$value"]["value"] = 701
            moved = build_core.load_breakpoints(self._write_doc(doc, tmp))
            self.assertEqual(moved["phone"], 700)
            self.assertEqual(moved["phone-up"], 701)
            changed = build_tokens.render_css(doc)
            self.assertIn("--bp-phone:700px;", changed)
            self.assertIn("--bp-phone-up:701px;", changed)

    def test_string_breakpoint_value_is_a_clear_error(self):
        doc = _doc()
        doc["misc"]["breakpoint"]["phone"]["$value"]["value"] = "700"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(build_core.CoreBuildError):
                build_core.load_breakpoints(self._write_doc(doc, tmp))
        with self.assertRaises(build_tokens.TokenError):
            build_tokens.render_css(doc)

    def test_non_numeric_breakpoint_value_is_a_clear_error(self):
        doc = _doc()
        doc["misc"]["breakpoint"]["md"]["$value"]["value"] = "900"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(build_core.CoreBuildError):
                build_core.load_breakpoints(self._write_doc(doc, tmp))
        with self.assertRaises(build_tokens.TokenError):
            build_tokens.render_css(doc)


class TestTokenMapComments(unittest.TestCase):
    def test_comment_only_reference_is_not_consumed(self):
        cases = [("/* var(--orphan) */", ".css"),
                 ("<!-- var(--orphan) -->", ".html"),
                 ("# var(--orphan)\n", ".py"),
                 ("// var(--orphan)\n", ".js")]
        for text, ext in cases:
            stripped = token_map.strip_comments(text, ext)
            self.assertEqual(token_map.VAR_RE.findall(stripped), [],
                             "%s comment leaked a consumer" % ext)

    def test_string_literal_reference_is_still_consumed(self):
        py = "STYLE = '<div style=\"font-family:var(--mono)\">x</div>'"
        self.assertEqual(token_map.VAR_RE.findall(token_map.strip_comments(py, ".py")), ["mono"])
        css = ".a{color:var(--acc)}"
        self.assertEqual(token_map.VAR_RE.findall(token_map.strip_comments(css, ".css")), ["acc"])

    def test_js_url_is_not_treated_as_a_comment(self):
        js = "var u = 'https://example.com/x';"
        self.assertIn("https://example.com", token_map.strip_comments(js, ".js"))

    def test_js_line_comment_is_string_aware(self):
        # a //cdn fragment inside a string must not swallow the next real use
        js = 'var u = "//cdn.example.com"; var(--real);'
        stripped = token_map.strip_comments(js, ".js")
        self.assertIn("//cdn.example.com", stripped)
        self.assertEqual(token_map.VAR_RE.findall(stripped), ["real"])
        # a genuine // comment must be stripped, hiding its var(--fake)
        fake = "var x = 1; // var(--fake)\n"
        self.assertEqual(token_map.VAR_RE.findall(token_map.strip_comments(fake, ".js")), [])
        # backtick and escaped quotes are string contexts too
        tpl = "var t = `//not a comment ${x}`; var(--real2);"
        self.assertEqual(token_map.VAR_RE.findall(token_map.strip_comments(tpl, ".js")), ["real2"])
        esc = "var e = 'a\\'//b'; var(--real3);"
        self.assertEqual(token_map.VAR_RE.findall(token_map.strip_comments(esc, ".js")), ["real3"])

    def test_metadata_entry_that_became_consumed_is_flagged(self):
        bad = token_map.violations({"orphan"}, {"orphan": ["some/file.css"]}, {"orphan": "reason"})
        self.assertTrue(any("remove the entry" in b for b in bad), bad)


class TestSpacingRolesAndLayout(unittest.TestCase):
    """The curated spacing roles and the layout dimension group drive output."""

    def test_spacing_role_value_drives_space_custom_property(self):
        doc = _doc()
        before = build_tokens.render_css(doc)
        self.assertIn("--space-page:24px;", before)
        doc["spacing"]["page"]["$value"]["value"] = 40
        after = build_tokens.render_css(doc)
        self.assertIn("--space-page:40px;", after)
        self.assertNotIn("--space-page:24px;", after)

    def test_layout_value_drives_layout_custom_property(self):
        doc = _doc()
        before = build_tokens.render_css(doc)
        self.assertIn("--layout-sidebar:236px;", before)
        self.assertIn("--layout-content-max:1160px;", before)
        doc["misc"]["layout"]["sidebar"]["$value"]["value"] = 220
        after = build_tokens.render_css(doc)
        self.assertIn("--layout-sidebar:220px;", after)
        self.assertNotIn("--layout-sidebar:236px;", after)

    def test_preferred_scale_32_step_is_emitted(self):
        out = build_tokens.render_css(_doc())
        self.assertIn("--space-32:32px;", out)

    def test_role_tokens_are_consumed_by_the_canonical_core(self):
        composed = build_core.compose(
            "core/base.css", ["base.css", "additions.css", "components.css"],
            build_core.load_breakpoints())
        for ref in ("var(--space-page)", "var(--space-card)", "var(--space-field)",
                    "var(--space-control)", "var(--layout-sidebar)",
                    "var(--layout-content-max)", "var(--layout-dock)"):
            self.assertIn(ref, composed, ref)


if __name__ == "__main__":
    unittest.main()
