from pathlib import Path
import importlib.util
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("repository_check", ROOT / "harness" / "check_repository.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class RepositoryBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="madb-lab-boundary-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_internal_fixture_dependency_is_allowed(self):
        (self.root / "Cargo.toml").write_text('[dependencies]\nfixture = { path = "fixtures/case" }\n')
        self.assertEqual(checker.dependency_errors(self.root), [])

    def test_private_crate_alias_is_rejected(self):
        (self.root / "Cargo.toml").write_text(
            '[target.\'cfg(unix)\'.dev-dependencies]\n'
            'alias = { package = "madb-model", version = "0.1" }\n')
        self.assertTrue(any("LAB006" in error for error in checker.dependency_errors(self.root)))

    def test_neighbor_workspace_dependency_is_rejected(self):
        (self.root / "Cargo.toml").write_text('[workspace.dependencies]\nhelper = { path = "../madb/helper" }\n')
        self.assertTrue(any("LAB007" in error for error in checker.dependency_errors(self.root)))

    def test_external_symlink_is_rejected(self):
        (self.root / "neighbor").symlink_to(self.root.parent, target_is_directory=True)
        self.assertTrue(any("LAB005" in error for error in checker.dependency_errors(self.root)))

    def test_registry_patch_cannot_hide_a_neighbor_dependency(self):
        (self.root / "Cargo.toml").write_text('[patch.crates-io]\nhelper = { path = "../private-helper" }\n')
        self.assertTrue(any("LAB007" in error for error in checker.dependency_errors(self.root)))

    def test_nested_readme_is_covered_by_snapshot_checksums(self):
        shutil.copytree(ROOT / "docs" / "reference", self.root / "docs" / "reference")
        reference = self.root / "docs" / "reference"
        self.assertEqual(checker.snapshot_errors(self.root), [])
        target = reference / "examples" / "first-route" / "README.md"
        target.write_text(target.read_text() + "\nUnexpected nested edit.\n")
        self.assertTrue(any("LAB003" in error for error in checker.snapshot_errors(self.root)))

    def test_snapshot_edits_are_rejected(self):
        shutil.copytree(ROOT / "docs" / "reference", self.root / "docs" / "reference")
        self.assertEqual(checker.snapshot_errors(self.root), [])
        target = self.root / "docs" / "reference" / "engineering" / "07-agent-development.md"
        with target.open("a") as output:
            output.write("\nChanged after pinning.\n")
        self.assertTrue(any("LAB003" in error for error in checker.snapshot_errors(self.root)))


if __name__ == "__main__":
    unittest.main()
