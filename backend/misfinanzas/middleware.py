import re
from django.http import HttpResponse
from django.utils.cache import patch_vary_headers


class BlockMaliciousRequestsMiddleware:
    """Drop or short-circuit very common automated probes (WordPress, .env, xmlrpc, etc.).

    This reduces app load and noise. It returns 404 (or 410) quickly without touching views.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # Precompile patterns seen in logs
        self.patterns = [
            re.compile(p, re.IGNORECASE)
            for p in (
                r"^/(wp-admin|wp-login\.php)(/|$)",
                r"^/(wordpress|wp|blog|cms|site|test|shop|wp2|2018|2020)/",
                r"/xmlrpc\.php$",
                r"/wlwmanifest\.xml$",
                r"/\.env$",
                r"/\.git/?",
                r"/\w+\.php$",
                r"/js/(lkk_ch|twint_ch)\.js$",
                r"/css/support_parent\.css$",
            )
        ]

    def __call__(self, request):
        path = (request.path or "").lower()
        for pat in self.patterns:
            if pat.search(path):
                # 410 Gone signals scanners this path isn't here
                return HttpResponse(status=410)
        return self.get_response(request)


class VaryOnCookieMiddleware:
    """Ensure HTML responses include `Vary: Cookie` and `Cache-Control: private`
    to avoid CDN/shared-cache serving pages with another user's CSRF token.

    This is a lightweight mitigation for cases where a reverse proxy or CDN
    might cache HTML pages and accidentally return a page containing a
    different user's CSRF token (causing "CSRF token from POST incorrect").
    
    Security note: HTML pages with CSRF tokens should NEVER be cached by
    shared caches (CDNs, proxies). We use:
    - Cache-Control: private, no-store - Tells browsers to cache locally only
    - Vary: Cookie - Tells caches that response varies by Cookie header
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        content_type = (response.get('Content-Type') or '').lower()
        if content_type.startswith('text/html'):
            # Add Vary: Cookie header
            patch_vary_headers(response, ['Cookie'])
            # Prevent shared caches from storing HTML pages with CSRF tokens
            # Allow browser cache but prevent CDN/proxy caching
            if not response.get('Cache-Control'):
                response['Cache-Control'] = 'private, no-store, max-age=0'
        return response
