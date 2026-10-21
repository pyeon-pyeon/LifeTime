import { useCallback, useEffect, useRef, useState } from 'react'
import type { Coordinates } from '../types/location'

type LocationState = {
  coordinates: Coordinates | null
  accuracy: number | null
  status: 'loading' | 'success' | 'error'
  error: string | null
}

export function useGeolocation() {
  const [state, setState] = useState<LocationState>({
    coordinates: null,
    accuracy: null,
    status: 'loading',
    error: null,
  })

  const mountedRef = useRef(false)
  const requestIdRef = useRef(0)

  const refresh = useCallback(() => {
    const requestId = ++requestIdRef.current

    if (!navigator.geolocation) {
      setState({
        coordinates: null,
        accuracy: null,
        status: 'error',
        error: '현재 위치를 지원하지 않는 브라우저입니다.',
      })
      return
    }

    setState((previous) => ({
      ...previous,
      status: 'loading',
      error: null,
    }))

    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (
          !mountedRef.current ||
          requestId !== requestIdRef.current
        ) {
          return
        }

        setState({
          coordinates: {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
          },
          accuracy: position.coords.accuracy,
          status: 'success',
          error: null,
        })
      },
      (error) => {
        if (
          !mountedRef.current ||
          requestId !== requestIdRef.current
        ) {
          return
        }

        const messages: Record<number, string> = {
          1: '위치 권한이 거부되었습니다. 브라우저의 사이트 설정에서 허용해 주세요.',
          2: '현재 위치를 확인할 수 없습니다. 다시 시도해 주세요.',
          3: '위치 확인 시간이 초과됐습니다. 다시 시도해 주세요.',
        }

        setState({
          coordinates: null,
          accuracy: null,
          status: 'error',
          error: messages[error.code] ?? '위치 확인에 실패했습니다.',
        })
      },
      {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 60000,
      },
    )
  }, [])

  useEffect(() => {
    mountedRef.current = true

    // 개발 모드의 Effect 재실행 시 중복 요청 방지
    const timer = window.setTimeout(refresh, 0)

    return () => {
      window.clearTimeout(timer)
      mountedRef.current = false
      requestIdRef.current += 1
    }
  }, [refresh])

  return {
    ...state,
    refresh,
  }
}