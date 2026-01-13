import logging
import re


class IgnoreCommon404(logging.Filter):
    """Filter out noisy 404 warnings from well-known bot probes.

    Matches the message content emitted by django.request: "Not Found: <path>".
    """

    def __init__(self, name: str = ""):
        super().__init__(name)
        self.regex = re.compile(
            r"/(wp-admin|wp-login\.php|xmlrpc\.php|wlwmanifest\.xml|wordpress/|wp/|blog/|cms/|site/|test/|shop/|wp2/|2018/|2020/|robots\.txt|favicon\.(ico|png)|\.env|js/(lkk_ch|twint_ch)\.js|css/support_parent\.css)",
            re.IGNORECASE,
        )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        # Allow non-404 warnings or messages not matching the common patterns
        if "Not Found:" in msg or "404" in msg:
            # Try to extract path from the message
            # Patterns look like: "Not Found: /wp-admin/setup-config.php"
            return not self.regex.search(msg)
        return True
