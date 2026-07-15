const seriesId = "GDP";

// ok: missing-encode-uri — encoded
fetch(`/api/series/${encodeURIComponent(seriesId)}/data`);

// ok: missing-encode-uri — static template, no interpolation
fetch(`/api/series/GDPC1/data`);

// ok: missing-encode-uri — non-fetch call
const url = `/api/series/${seriesId}/data`;
