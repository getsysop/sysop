import httpx

# ruleid: http-client-redirect
httpx.Client(timeout=5)

# ruleid: http-client-redirect
httpx.AsyncClient()

# ruleid: http-client-redirect
httpx.Client(base_url="https://example.com")
