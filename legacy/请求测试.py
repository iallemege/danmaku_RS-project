# Optional debug proxy helper. Keep TLS verification enabled unless you
# are intercepting traffic on a local trusted proxy.

def apply_debug_proxy(session, proxy="http://127.0.0.1:8888", verify=True):
    session.proxies = {
        "http": proxy,
        "https": proxy,
    }
    session.verify = verify
    return session
