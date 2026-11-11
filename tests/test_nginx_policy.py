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

    def test_public_alias_only_adapts_an_exact_origin_on_the_public_endpoint(self):
        policy = (
            Path(__file__).parents[1] / "ops/nginx/jardines-domain.conf"
        ).read_text()
        registration = policy.split("location = /api/landing/registrations {", 1)[1]
        registration = registration.split("location ^~ /api/", 1)[0]
        guard = 'if ($http_origin != "https://jardinesdelencanto.site") { return 403; }'
        adaptation = 'proxy_set_header Origin "https://jardines.2.24.111.40.sslip.io";'
        self.assertLess(registration.index(guard), registration.index(adaptation))
        self.assertEqual(policy.count(adaptation), 1)
        self.assertIn('proxy_set_header Cookie "";', registration)
        self.assertIn('proxy_set_header Authorization "";', registration)
        self.assertIn("location ^~ /api/ { return 404; }", policy)
        self.assertIn("proxy_temp_path /var/lib/nginx/jardines-proxy 1 2;", policy)
        self.assertIn('"$request_method $uri $server_protocol"', policy)
        self.assertNotIn("$http_referer", policy)
        self.assertIn("/etc/letsencrypt/live/jardines-domain/fullchain.pem", policy)

    def test_indexing_is_allowlisted_only_on_the_public_domain(self):
        root = Path(__file__).parents[1] / "ops/nginx"
        policy = (root / "jardines-domain.conf").read_text()
        indexing = policy.split("map $uri $jardines_domain_robots {", 1)[1].split("}", 1)[0]
        self.assertIn('default "noindex, nofollow";', indexing)
        for path in ["/", "/lotes-acacias-desde-bogota-soacha", "/robots.txt", "/sitemap.xml"]:
            self.assertIn(f'{path} "";', indexing)
        self.assertNotIn('/crm "";', indexing)
        self.assertNotIn('/login "";', indexing)
        self.assertIn("add_header X-Robots-Tag $jardines_domain_robots always;", policy)
        self.assertIn('add_header X-Robots-Tag "noindex, nofollow" always;', (root / "jardines-preview.conf").read_text())


if __name__ == "__main__":
    unittest.main()
