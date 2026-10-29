// ok: error-display-jsx — logging, not rendering
function handleError(err: Error) {
  console.error(err.message);
  throw new Error(err.message);
}

// ok: error-display-jsx — using getDisplayError
function ErrorA({ err }: { err: Error }) {
  return <div>{getDisplayError(err)}</div>;
}

// ok: error-display-jsx — no JSX, pure assignment
function getMsg(error: Error) {
  const msg = error.message;
  return msg;
}
