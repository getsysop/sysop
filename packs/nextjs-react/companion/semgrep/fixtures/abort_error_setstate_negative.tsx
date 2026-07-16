import { useEffect, useState } from 'react';
import { isAbortError } from '../lib/errorMessages';

declare function abortableFetch(url: string): Promise<Response>;

// Negative 1: AbortError branch returns immediately without setState — correct
export function NegativeReturn() {
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        async function load() {
            try {
                const res = await abortableFetch('/api/x');
                const json = await res.json();
                if (!cancelled) {
                    setData(json);
                    setLoading(false);
                }
            } catch (err) {
                if (isAbortError(err)) return;
                if (!cancelled) setLoading(false);
            }
        }
        load();
        return () => { cancelled = true; };
    }, []);

    return <div>{data}</div>;
}

// Negative 2: callback context (NOT useEffect) — convention requires setState
export function NegativeCallback() {
    const [loading, setLoading] = useState(false);

    const handleClick = async () => {
        setLoading(true);
        try {
            await abortableFetch('/api/x');
        } catch (err) {
            if (isAbortError(err)) {
                setLoading(false);  // ← OK: callback context, no useEffect cleanup
                return;
            }
        } finally {
            setLoading(false);
        }
    };

    return <button onClick={handleClick}>{loading ? '...' : 'Go'}</button>;
}
