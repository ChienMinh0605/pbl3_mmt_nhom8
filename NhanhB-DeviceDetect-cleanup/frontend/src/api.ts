export async function apiRequest<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch('/api/' + path, {method, headers: {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store', signal});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data as T;
}
