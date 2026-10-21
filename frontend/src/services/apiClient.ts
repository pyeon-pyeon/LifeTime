const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? ''
).trim().replace(/\/+$/, '')

export async function apiGet(
  path: string,
  signal?: AbortSignal,
): Promise<unknown> {
  if (!API_BASE_URL) {
    throw new Error('VITE_API_BASE_URL 설정을 확인해 주세요.')
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
    },
    cache: 'no-store',
    signal,
  })

  if (!response.ok) {
    const messages: Record<number, string> = {
      404: '요청한 정보를 찾을 수 없습니다.',
      422: '검색 좌표나 조건이 올바르지 않습니다.',
      503: '시설 DB를 조회하지 못했습니다.',
    }

    throw new Error(
      messages[response.status] ??
        `API 요청에 실패했습니다. (${response.status})`,
    )
  }

  return response.json()
}