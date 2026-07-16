import { useEffect, useState } from 'react';
import { isAbortError } from '../lib/errorMessages';

declare function abortableFetch(url: string): Promise<Response>;

export function PositiveCase() {
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
                if (isAbortError(err)) {
                    setLoading(false);  // ← FLAG: setState in AbortError branch without guard
                    return;
                }
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }
        load();
        return () => { cancelled = true; };
    }, []);

    return <div>{data}</div>;
}
