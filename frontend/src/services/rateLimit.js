export const RATE_LIMIT_EVENT = 'lifetime:rate-limit'
export const RATE_LIMIT_MESSAGE = '요청이 많습니다. 잠시 후 다시 시도해 주세요.'

const FALLBACK_RETRY_SECONDS = 60
const MAX_RETRY_SECONDS = 3600

export function parseRetryAfter(value, now = Date.now()) {
  if (typeof value !== 'string' || !value.trim()) return FALLBACK_RETRY_SECONDS

  const trimmed = value.trim()
  let seconds
  if (/^\d+$/.test(trimmed)) {
    seconds = Number(trimmed)
  } else {
    const date = Date.parse(trimmed)
    if (!Number.isFinite(date)) return FALLBACK_RETRY_SECONDS
    seconds = Math.ceil((date - now) / 1000)
  }

  if (!Number.isFinite(seconds)) return FALLBACK_RETRY_SECONDS
  return Math.min(MAX_RETRY_SECONDS, Math.max(1, Math.ceil(seconds)))
}

export class RateLimitCooldown {
  #until = 0

  blockFor(seconds, now = Date.now()) {
    const normalized = Math.min(
      MAX_RETRY_SECONDS,
      Math.max(1, Math.ceil(Number(seconds) || FALLBACK_RETRY_SECONDS)),
    )
    this.#until = Math.max(this.#until, now + normalized * 1000)
    return this.#until
  }

  remainingSeconds(now = Date.now()) {
    return Math.max(0, Math.ceil((this.#until - now) / 1000))
  }

  clear() {
    this.#until = 0
  }
}

export class RateLimitError extends Error {
  constructor(retryAfterSeconds) {
    super(`${RATE_LIMIT_MESSAGE} ${retryAfterSeconds}초 후 다시 시도할 수 있습니다.`)
    this.name = 'RateLimitError'
    this.retryAfterSeconds = retryAfterSeconds
  }
}

export const routeRequestCooldown = new RateLimitCooldown()

function announceRateLimit(retryAfterSeconds, until) {
  if (typeof window === 'undefined' || typeof CustomEvent === 'undefined') return
  window.dispatchEvent(new CustomEvent(RATE_LIMIT_EVENT, {
    detail: { retryAfterSeconds, until },
  }))
}

export async function fetchRateLimited(input, init) {
  const remaining = routeRequestCooldown.remainingSeconds()
  if (remaining > 0) throw new RateLimitError(remaining)

  const response = await fetch(input, init)
  if (
    response.status === 429 &&
    response.headers.get('X-RateLimit-Source') === 'lifetime'
  ) {
    const retryAfterSeconds = parseRetryAfter(response.headers.get('Retry-After'))
    const until = routeRequestCooldown.blockFor(retryAfterSeconds)
    announceRateLimit(routeRequestCooldown.remainingSeconds(), until)
    throw new RateLimitError(routeRequestCooldown.remainingSeconds())
  }

  return response
}
