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

    def test_public_capture_guards_origin_without_rewriting_it(self):
        policy = (Path(__file__).parents[1] / "ops/nginx/jardines-domain.conf").read_text()
        registration = policy.split("location = /api/landing/registrations {", 1)[1]
        registration = registration.split("location ^~ /api/", 1)[0]
        self.assertIn('if ($http_origin != "https://jardinesdelencanto.site") { return 403; }', registration)
        self.assertNotIn("proxy_set_header Origin", policy)
        self.assertIn('proxy_set_header Cookie "";', registration)
        self.assertIn('proxy_set_header Authorization "";', registration)
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


class CanonicalCrmTests(unittest.TestCase):
    def test_login_and_crm_are_served_on_the_branded_origin(self):
        root = Path(__file__).parents[1]
        policy = (root / "ops/nginx/jardines-domain.conf").read_text()
        self.assertNotIn("return 302 https://jardines.2.24.111.40.sslip.io", policy)
        self.assertNotIn("proxy_set_header Origin", policy)
        self.assertIn("location ^~ /api/ {", policy)
        self.assertIn("location = /crm {", policy)
        self.assertIn("error_log /dev/null;", policy)
        compose = (root / "ops/crm.compose.yaml").read_text()
        self.assertIn("CRM_ORIGIN: https://jardinesdelencanto.site", compose)
        self.assertNotIn("CRM_ORIGIN: https://jardines.2.24.111.40.sslip.io", compose)
        provision = (root / "ops/crm-provision.py").read_text()
        self.assertIn('ORIGIN = "https://jardinesdelencanto.site"', provision)

    def test_legacy_origin_redirects_documents_but_never_posts_credentials(self):
        policy = (Path(__file__).parents[1] / "ops/nginx/jardines-preview.conf").read_text()
        self.assertIn("return 308 https://jardinesdelencanto.site$request_uri;", policy)
        self.assertIn("location ^~ /api/ { return 403; }", policy)
        self.assertIn("location = /api/integrations/zernio/webhook {", policy)
        self.assertIn('if ($request_method !~ ^(GET|HEAD)$) { return 405; }', policy)
        self.assertNotIn("proxy_set_header Origin", policy)


if __name__ == "__main__":
    unittest.main()


class ReviewCapabilityLogTests(unittest.TestCase):
    def test_capability_access_and_error_logs_are_disabled_only_for_that_prefix(self):
        policy = (Path(__file__).parents[1] / 'ops/nginx/jardines-domain.conf').read_text()
        capability = policy.split('location ^~ /api/crm/campaigns/review-media/ {', 1)[1].split('}', 1)[0]
        self.assertIn('access_log off;', capability)
        self.assertIn('error_log /dev/null;', capability)
        self.assertIn('proxy_pass http://127.0.0.1:13400;', capability)
