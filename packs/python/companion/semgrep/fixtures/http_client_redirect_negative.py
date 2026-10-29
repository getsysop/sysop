import httpx

# ok: http-client-redirect — follow_redirects set (matches isr_client.py:39 pattern)
httpx.Client(timeout=5, follow_redirects=False)

# ok: http-client-redirect — follow_redirects set
httpx.AsyncClient(follow_redirects=False)

# ok: http-client-redirect — multi-line constructor with follow_redirects (matches watchdog.py:43-45 style)
httpx.Client(
    timeout=30,
    follow_redirects=False,
)
