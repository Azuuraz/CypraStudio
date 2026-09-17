import io
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import server


class StartupBuildTests(unittest.TestCase):
    def test_desktop_accepts_current_server_health(self):
        health = io.BytesIO(json.dumps(server.health()).encode())
        with patch('urllib.request.urlopen', return_value=health):
            self.assertTrue(app.health_ok(8765))

    def test_launcher_uses_current_build(self):
        launcher = (Path(__file__).resolve().parents[1] / 'START.ps1').read_text(encoding='utf-8-sig')
        build = re.search(r'\$BuildId = "([^"]+)"', launcher).group(1)
        self.assertEqual(build, server.BUILD_ID)
