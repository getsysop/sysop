// Negative fixture: nothing here may be flagged by window-open-noopener.
declare const url: string;

export function good() {
  window.open(url, '_blank', 'noopener,noreferrer');
  window.open(url, '_blank', 'noopener');
  window.open(url, '_blank', 'width=400,noopener,height=300');
  // The wrapped-call shape, safely spelled — the per-line grep twin reports
  // this one as a finding and needs a hand-written waiver; the AST rule does
  // not, which is the whole reason this rule exists alongside it.
  window.open(
    url,
    '_blank',
    'noopener,noreferrer',
  );
}

// A comment mentioning window-open-noopener and the word noopener must not
// change any verdict above.
