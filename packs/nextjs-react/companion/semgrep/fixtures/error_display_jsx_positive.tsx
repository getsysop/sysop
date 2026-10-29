// ruleid: error-display-jsx
function ErrorA({ err }: { err: Error }) {
  return <div>{err.message}</div>;
}

// ruleid: error-display-jsx
function ErrorB({ error }: { error: Error }) {
  return <p>{error.message}</p>;
}

// ruleid: error-display-jsx
function ErrorC({ err }: { err: Error }) {
  return <span className="err">{err.message}</span>;
}
