import unittest
from fastapi.testclient import TestClient

from server import app


class ServerSecurityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url='http://127.0.0.1:8765', client=('127.0.0.1', 50123))

    def test_health_has_browser_security_headers(self):
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('x-frame-options'), 'DENY')
        self.assertEqual(response.headers.get('x-content-type-options'), 'nosniff')
        self.assertIn("default-src 'self'", response.headers.get('content-security-policy', ''))
        self.assertEqual(response.headers.get('cache-control'), 'no-store')

    def test_non_loopback_host_header_is_blocked(self):
        response = self.client.get('/api/health', headers={'host': 'evil.example'})
        self.assertEqual(response.status_code, 403)

    def test_cross_site_get_is_blocked(self):
        response = self.client.get('/api/health', headers={'sec-fetch-site': 'cross-site'})
        self.assertEqual(response.status_code, 403)

    def test_cross_origin_state_change_is_blocked(self):
        response = self.client.post(
            '/api/tts/stop',
            headers={'origin': 'https://evil.example'},
            json={'release': False},
        )
        self.assertEqual(response.status_code, 403)

    def test_same_origin_state_change_is_allowed(self):
        response = self.client.post(
            '/api/tts/stop',
            headers={'origin': 'http://127.0.0.1:8765'},
            json={'release': False},
        )
        self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()
