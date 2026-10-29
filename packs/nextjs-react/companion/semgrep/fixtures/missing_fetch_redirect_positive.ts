// Positive fixtures — each should be flagged by missing-fetch-redirect.

const url = "/api/example";

// ruleid: missing-fetch-redirect — one-arg fetch (no options object)
fetch(url);

// ruleid: missing-fetch-redirect — options object without redirect
fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
});

// ruleid: missing-fetch-redirect — explicit redirect: 'follow' is not allowed
fetch(url, {
    method: "GET",
    redirect: "follow",
});
