from html import escape


GENERATED_HTML_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data: blob:; font-src data:; frame-src about:; "
    "connect-src 'none'; base-uri 'none'; form-action 'none'"
)
GENERATED_HTML_META = (
    '<meta http-equiv="Content-Security-Policy" '
    f'content="{escape(GENERATED_HTML_CSP, quote=True)}">'
)
