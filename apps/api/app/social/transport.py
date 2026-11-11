"""Fixed vendor HTTPS with optional project-private, end-to-end TLS tunneling."""
import http.client
import os

HOSTS = frozenset({'zernio.com', 'mcp.zernio.com'})
PROXY = 'http://zernio-egress:8080'


def https_connection(host, timeout):
    """Never use ambient HTTP(S)_PROXY or caller-supplied proxy destinations."""
    if not isinstance(host, str) or host not in HOSTS:
        raise ValueError('Unsupported Zernio target')
    proxy = os.environ.get('ZERNIO_HTTPS_PROXY')
    if proxy is None:
        return http.client.HTTPSConnection(host, timeout=timeout)
    if proxy != PROXY:
        raise ValueError('Invalid Zernio HTTPS proxy configuration')
    # HTTPSConnection wraps the established CONNECT stream with default verified
    # TLS and uses _tunnel_host for SNI/hostname verification, not the proxy name.
    connection = http.client.HTTPSConnection('zernio-egress', 8080, timeout=timeout)
    connection.set_tunnel(host, 443)
    return connection
