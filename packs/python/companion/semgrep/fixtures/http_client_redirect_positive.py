import httpx

# ruleid: http-client-redirect
httpx.Client(timeout=5)

# ruleid: http-client-redirect
httpx.AsyncClient()

# ruleid: http-client-redirect
httpx.Client(base_url="https://example.com")

# ruleid: http-client-redirect — set, but to the unsafe value
httpx.Client(follow_redirects=True)

# ruleid: http-client-redirect — set to the unsafe value among other kwargs
httpx.AsyncClient(timeout=3, follow_redirects=True)

# ruleid: http-client-redirect — a name the rule cannot prove is False
httpx.Client(follow_redirects=allow_redirects)
