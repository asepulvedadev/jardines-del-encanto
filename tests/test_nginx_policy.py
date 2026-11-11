"""Keep response buffering isolated from shared host temporary directories."""

from pathlib import Path
import unittest


class PreviewBufferingTests(unittest.TestCase):
    def test_https_uses_project_specific_proxy_temporary_directory(self):
        policy = (
            Path(__file__).parents[1] / "ops/nginx/jardines-preview.conf"
        ).read_text()
        https = policy.split("listen 443 ssl;", 1)[1]
        self.assertIn(
            "proxy_temp_path /var/lib/nginx/jardines-proxy 1 2;", https
        )
        self.assertNotIn("proxy_buffering off;", https)
        self.assertIn("location = /crm", https)
        self.assertIn("error_log /dev/null;", https)


if __name__ == "__main__":
    unittest.main()
