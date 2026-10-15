import unittest

from main import DEBLOAT_RECOMMENDATIONS, OEM_DEBLOAT_GUIDE, Package, parse_package_names


class ParsePackageNamesTests(unittest.TestCase):
    def test_parses_package_manager_output(self):
        output = "package:com.example.first\npackage:com.example.second\n"
        self.assertEqual(parse_package_names(output), ["com.example.first", "com.example.second"])

    def test_ignores_noise_and_empty_lines(self):
        output = "List of packages:\n\nnot-a-package\npackage:\n package:com.example.valid\n"
        self.assertEqual(parse_package_names(output), ["com.example.valid"])

    def test_deduplicates_packages_without_changing_order(self):
        output = "package:com.example.one\npackage:com.example.two\npackage:com.example.one\n"
        self.assertEqual(parse_package_names(output), ["com.example.one", "com.example.two"])

    def test_empty_output_returns_empty_list(self):
        self.assertEqual(parse_package_names(""), [])

    def test_package_model_defaults_are_safe(self):
        package = Package("com.example.app", "Third-party")
        self.assertEqual(package.recommendation, "Not listed")
        self.assertEqual(package.recommendation_note, "")

    def test_debloat_guidance_is_explicitly_conditional(self):
        self.assertIn("org.lineageos.aperture", DEBLOAT_RECOMMENDATIONS)
        risk, note = DEBLOAT_RECOMMENDATIONS["org.lineageos.aperture"]
        self.assertIn("verify", risk.casefold())
        self.assertIn("without", note.casefold())


class OEMDebloatGuideTests(unittest.TestCase):
    def test_guide_entries_have_required_fields(self):
        required = {"package", "app", "function", "risk", "impact"}
        self.assertTrue(OEM_DEBLOAT_GUIDE)
        for entry in OEM_DEBLOAT_GUIDE:
            with self.subTest(package=entry.get("package")):
                self.assertTrue(required.issubset(entry))
                self.assertTrue(entry["package"].strip())
                self.assertTrue(entry["app"].strip())
                self.assertTrue(entry["risk"].strip())

    def test_guide_package_ids_are_unique(self):
        package_ids = [entry["package"] for entry in OEM_DEBLOAT_GUIDE]
        self.assertEqual(len(package_ids), len(set(package_ids)))

    def test_core_packages_are_marked_to_keep(self):
        by_package = {entry["package"]: entry for entry in OEM_DEBLOAT_GUIDE}
        for package in (
            "com.android.systemui",
            "com.android.settings",
            "com.android.providers.telephony",
            "com.google.android.gms",
        ):
            with self.subTest(package=package):
                self.assertIn(package, by_package)
                risk = by_package[package]["risk"].casefold()
                self.assertTrue("critical" in risk or "high" in risk or "keep" in risk)


if __name__ == "__main__":
    unittest.main()
