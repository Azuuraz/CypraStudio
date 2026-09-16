from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LauncherTTSContractTests(unittest.TestCase):
    def test_edge_dependency_is_optional_and_only_prepared_when_configured(self):
        ps = (ROOT / 'START.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('function Prepare-OptionalEdgeTTS', ps)
        self.assertIn('edge-tts>=6.1,<8', ps)
        self.assertIn('Prepare-OptionalEdgeTTS', ps.split('Prepare-Python', 1)[-1])

    def test_requirements_declares_edge_tts_for_full_setup(self):
        req = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
        self.assertIn('edge-tts>=6.1,<8', req)


if __name__ == '__main__':
    unittest.main()
