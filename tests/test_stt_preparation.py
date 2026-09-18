import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from stt.service import LocalSTTService


class PreparationTests(unittest.TestCase):
    def test_stalled_download_reports_error_and_can_retry(self):
        with tempfile.TemporaryDirectory() as root:
            service = LocalSTTService(Path(root))
            whisper = types.ModuleType('faster_whisper')
            whisper.WhisperModel = Mock(return_value=object())
            utils = types.ModuleType('faster_whisper.utils')
            utils.download_model = Mock(side_effect=FileNotFoundError('not cached'))
            with patch.dict(sys.modules, {'faster_whisper': whisper, 'faster_whisper.utils': utils}), patch.object(service, 'dependency_available', return_value=True), patch('stt.service.subprocess.run', side_effect=subprocess.TimeoutExpired('download', 600)):
                service.begin_prepare(allow_install=True, allow_download=True)
                service._prepare_thread.join(2)
                status = service.status()
                self.assertEqual(status['prepare_state'], 'error')
                self.assertFalse(status['preparing'])
                self.assertFalse(status['model_ready'])
                self.assertIn('timed out', status['last_error'])
            model_dir = Path(root) / 'cached'
            model_dir.mkdir()
            for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'):
                (model_dir / name).write_text('data')
            utils.download_model = Mock(return_value=str(model_dir))
            with patch.dict(sys.modules, {'faster_whisper': whisper, 'faster_whisper.utils': utils}), patch.object(service, 'dependency_available', return_value=True), patch('stt.service.subprocess.run', side_effect=AssertionError('cached model must not download')):
                service.begin_prepare(allow_install=True, allow_download=True)
                service._prepare_thread.join(2)
                self.assertTrue(service.status()['model_ready'])

    def test_partial_cache_is_not_ready_when_downloads_disabled(self):
        with tempfile.TemporaryDirectory() as root:
            service = LocalSTTService(Path(root))
            whisper = types.ModuleType('faster_whisper')
            whisper.WhisperModel = Mock(return_value=object())
            utils = types.ModuleType('faster_whisper.utils')
            utils.download_model = Mock(return_value=root)
            with patch.dict(sys.modules, {'faster_whisper': whisper, 'faster_whisper.utils': utils}), patch.object(service, 'dependency_available', return_value=True):
                self.assertFalse(service.prepare(allow_install=False, allow_download=False))
                self.assertFalse(service.status()['model_ready'])
