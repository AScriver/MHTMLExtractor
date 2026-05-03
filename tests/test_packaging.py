import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None


class PackagingTests(unittest.TestCase):
    @unittest.skipIf(tomllib is None, "tomllib is only available on Python 3.11+")
    def test_pyproject_defines_installable_package_metadata(self):
        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"

        self.assertTrue(pyproject_path.exists(), "pyproject.toml should exist")
        metadata = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

        project = metadata["project"]
        self.assertEqual(project["name"], "MHTMLExtractor")
        self.assertEqual(project["requires-python"], ">=3.7")
        self.assertIn("mhtml", project["keywords"])
        self.assertIn("mhtml-extract", project["scripts"])
        self.assertEqual(project["scripts"]["mhtml-extract"], "mhtmlextractor.cli:main")
        self.assertIn("mhtmlextractor", metadata["tool"]["setuptools"]["packages"])
        self.assertIn("MHTMLExtractor", metadata["tool"]["setuptools"]["py-modules"])


if __name__ == "__main__":
    unittest.main()
