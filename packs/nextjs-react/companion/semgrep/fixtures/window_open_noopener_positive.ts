// Positive fixture: every call here MUST be flagged by window-open-noopener.
declare const url: string;
declare const feats: string;

export function bad() {
  // 1. no arguments at all
  // ruleid: window-open-noopener
  window.open();
  // 2. url only — no options, so no redirect guard
  // ruleid: window-open-noopener
  window.open(url);
  // 3. url + target, still no features string
  // ruleid: window-open-noopener
  window.open(url, '_blank');
  // 4. features string that omits noopener
  // ruleid: window-open-noopener
  window.open(url, '_blank', 'noreferrer,width=400');
  // 5. features passed as a variable — the rule cannot see through the
  //    binding, and flagging is the safe direction
  // ruleid: window-open-noopener
  window.open(url, '_blank', feats);
  // 6. the wrapped-call shape the per-line grep twin structurally cannot judge
  // ruleid: window-open-noopener
  window.open(
    url,
    '_blank',
    'width=400,height=300',
  );
}

// Round finding: `noopener` as a SUBSTRING is not `noopener` as a token.
// Both of these are unsafe and both passed the bare-substring form.
export function substringNotToken(u: string) {
  // ruleid: window-open-noopener
  window.open(u, '_blank', 'width=200,noopenerX');
  // ruleid: window-open-noopener
  window.open(u, '_blank', 'my-noopener-thing');
}
