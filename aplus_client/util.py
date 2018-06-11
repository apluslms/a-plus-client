from urllib.parse import SplitResult, urlsplit


HOSTS_LOCALHOSTS = ('localhost', '127.0.0.1')
HOSTS_TESTDOMAIN = ('testserver', 'testserver.testserver')
HOSTS_NONPUBLIC = HOSTS_LOCALHOSTS + HOSTS_TESTDOMAIN


def is_relative_url(url):
    if not isinstance(url, SplitResult):
        url = urlsplit(url)
    return not url.netloc


def is_localhost(domain):
    return (
        domain in ('localhost', 'localhost.localdomain') or
        # FIXME: naive test, matches 127.sub.example.com
        (domain.startswith('127.') and domain.count('.') == 3)
    )


def is_bad_url(url):
    if not isinstance(url, SplitResult):
        url = urlsplit(url)
    hostname = url.hostname
    return (
        is_relative_url(url) or
        is_localhost(hostname) or
        hostname in HOSTS_TESTDOMAIN
    )


def urlsplit_clean(url):
    url = urlsplit(url)
    if not url.netloc:
        raise AttributeError("Invalid URL for api client: no network location")
    if not url.scheme:
        port = url.port
        if not port:
            scheme = 'http' if is_localhost(url.hostname) else 'https'
        elif port in (80, 443):
            scheme = 'http' if port == 80 else 'https'
        else:
            raise AttributeError("Invalid URL for api client: no scheme with uncommon port")
        url = url._replace(scheme=scheme)
    return url


