// Live job stream over SSE. The /jobs/{id}/stream endpoint is public (no admin
// token) and emits three frame kinds (server.py:_log_stream):
//   data: <line>                       runner progress log lines
//   event: text / data: <delta>        engine text deltas (token streaming)
//   event: done / data: <status>       terminal marker
// EventSource cannot set headers, which is fine here since the endpoint is open.

export interface JobStreamHandlers {
  onLog?: (line: string) => void;
  onText?: (delta: string) => void;
  onDone?: (status: string) => void;
  onError?: () => void;
}

export function openJobStream(jobId: string, h: JobStreamHandlers): () => void {
  const es = new EventSource(`/jobs/${jobId}/stream`);

  es.onmessage = (e) => h.onLog?.(e.data);
  es.addEventListener("text", (e) => h.onText?.((e as MessageEvent).data));
  es.addEventListener("done", (e) => {
    h.onDone?.((e as MessageEvent).data);
    es.close();
  });
  es.onerror = () => {
    h.onError?.();
    es.close();
  };

  return () => es.close();
}
