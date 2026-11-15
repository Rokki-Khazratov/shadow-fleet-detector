export const demoMode = new URLSearchParams(window.location.search).get('demo') === '1';

export async function request(path: string, init?: RequestInit): Promise<Response> {
  if (!demoMode) return fetch(path, init);
  const {demoResponse} = await import('./demo');
  init?.signal?.throwIfAborted();
  return demoResponse(path);
}
