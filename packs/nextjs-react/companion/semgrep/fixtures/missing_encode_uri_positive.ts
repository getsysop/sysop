const seriesId = "GDP";

// ruleid: missing-encode-uri
fetch(`/api/series/${seriesId}/data`);

// ruleid: missing-encode-uri
const slug = "some-slug";
fetch(`/api/embed/${slug}`);
