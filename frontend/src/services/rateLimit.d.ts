export const RATE_LIMIT_EVENT: string
export const RATE_LIMIT_MESSAGE: string

export function parseRetryAfter(value: string | null, now?: number): number

export class RateLimitCooldown {
  blockFor(seconds: number, now?: number): number
  remainingSeconds(now?: number): number
  clear(): void
}

export class RateLimitError extends Error {
  retryAfterSeconds: number
}

export const routeRequestCooldown: RateLimitCooldown

export function fetchRateLimited(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response>
