import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import server
from tts.service import LocalTTSService


class TTSEdgePrepareTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, base_url='http://127.0.0.1:8765', client=('127.0.0.1', 50124))

    def test_prepare_endpoint_installs_only_after_online_gate(self):
        with patch('server.load_settings', return_value={'tts_allow_online': False}), \
             patch.object(server.LOCAL_TTS, 'prepare_edge_dependency') as prepare:
            blocked = self.client.post('/api/tts/edge/prepare')
        self.assertEqual(blocked.status_code, 409)
        prepare.assert_not_called()

        with patch('server.load_settings', return_value={'tts_allow_online': True}), \
             patch.object(server.LOCAL_TTS, 'prepare_edge_dependency', return_value=True) as prepare:
            ready = self.client.post('/api/tts/edge/prepare')
        self.assertEqual(ready.status_code, 200)
        self.assertTrue(ready.json()['ready'])
        prepare.assert_called_once_with(allow_install=True)

    def test_dependency_prepare_uses_current_project_python_and_hardcoded_package(self):
        service = LocalTTSService(server.ROOT)
        with patch.object(service, '_edge_available', side_effect=[False, False, True]), \
             patch('tts.service.subprocess.run') as run:
            run.return_value.returncode = 0
            result = service.prepare_edge_dependency(allow_install=True)
        self.assertTrue(result)
        args = run.call_args.args[0]
        self.assertEqual(args[:3], [sys.executable, '-m', 'pip'])
        self.assertIn('edge-tts>=6.1,<8', args)
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_dependency_prepare_never_installs_when_online_permission_is_closed(self):
        service = LocalTTSService(server.ROOT)
        with patch.object(service, '_edge_available', return_value=False), patch('tts.service.subprocess.run') as run:
            self.assertFalse(service.prepare_edge_dependency(allow_install=False))
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
