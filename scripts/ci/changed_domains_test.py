from __future__ import annotations

import unittest

from changed_domains import classify


class ChangedDomainsTest(unittest.TestCase):
    def test_docs_only_skips_all_heavy_domains(self) -> None:
        self.assertEqual(
            classify(["docs/contracts.md", "README.md", "implementation_plans/x.md"]),
            {
                "backend": False,
                "frontend": False,
                "security": False,
                "container": False,
            },
        )

    def test_backend_tests_skip_the_container_image(self) -> None:
        domains = classify(["backend/tests/test_controller.py"])
        self.assertTrue(domains["backend"])
        self.assertTrue(domains["security"])
        self.assertFalse(domains["frontend"])
        self.assertFalse(domains["container"])

    def test_frontend_tests_skip_the_container_image(self) -> None:
        domains = classify(["frontend/tests/markdown.test.tsx"])
        self.assertFalse(domains["backend"])
        self.assertTrue(domains["frontend"])
        self.assertTrue(domains["security"])
        self.assertFalse(domains["container"])

    def test_application_change_runs_backend_frontend_security_and_image(self) -> None:
        domains = classify(["backend/app/main.py", "frontend/src/App.tsx"])
        self.assertTrue(all(domains.values()))

    def test_build_and_e2e_inputs_run_the_container(self) -> None:
        for path in ("Dockerfile", "compose.yaml", "tests/e2e/workbench.spec.ts"):
            domains = classify([path])
            self.assertTrue(domains["container"], path)
            self.assertTrue(domains["security"], path)

    def test_vendor_and_lock_changes_run_the_frontend(self) -> None:
        domains = classify(
            ["vendor/triage/core/base.css", "frontend/package-lock.json"]
        )
        self.assertTrue(domains["frontend"])
        self.assertTrue(domains["container"])
        self.assertTrue(domains["security"])

    def test_workflow_changes_are_security_only(self) -> None:
        for path in (".github/workflows/ci.yml", ".github/workflows/deploy.yml"):
            self.assertEqual(
                classify([path]),
                {
                    "backend": False,
                    "frontend": False,
                    "security": True,
                    "container": False,
                },
            )


if __name__ == "__main__":
    unittest.main()
