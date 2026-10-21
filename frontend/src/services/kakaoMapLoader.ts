let sdkPromise: Promise<void> | null = null

export function loadKakaoMap(): Promise<void> {
  if (sdkPromise) return sdkPromise

  const appKey = import.meta.env.VITE_KAKAO_MAP_APP_KEY?.trim()

  if (!appKey) {
    return Promise.reject(
      new Error('.env.local의 VITE_KAKAO_MAP_APP_KEY를 확인해 주세요.'),
    )
  }

  sdkPromise = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')

    const timeout = window.setTimeout(() => {
      script.remove()
      reject(
        new Error('지도 로딩 시간이 초과됐습니다. 키·도메인 설정을 확인해 주세요.'),
      )
    }, 15000)

    script.src =
      'https://dapi.kakao.com/v2/maps/sdk.js' +
      `?appkey=${encodeURIComponent(appKey)}&autoload=false`

    script.async = true

    script.onload = () => {
      if (!window.kakao?.maps) {
        window.clearTimeout(timeout)
        reject(new Error('카카오 지도 SDK를 초기화하지 못했습니다.'))
        return
      }

      window.kakao.maps.load(() => {
        window.clearTimeout(timeout)
        resolve()
      })
    }

    script.onerror = () => {
      window.clearTimeout(timeout)
      script.remove()
      reject(new Error('지도 SDK를 불러오지 못했습니다. 네트워크를 확인해 주세요.'))
    }

    document.head.appendChild(script)
  })

  return sdkPromise
}