import { useEffect, useRef, useState } from 'react'
import type { Facility } from '../types/facility'
import type { Coordinates } from '../types/location'
import { loadKakaoMap } from '../services/kakaoMapLoader'
import Icon from './Icon'
import type { WalkingRoute } from '../types/route'
import type { WalkingRanks } from '../types/ranking'


type FacilityMapProps = {
  facilities: Facility[]
  selectedId: string | null
  currentLocation: Coordinates | null
  searchLocation: Coordinates | null
  walkingRoute: WalkingRoute | null
  locating: boolean
  walkingRanks: WalkingRanks
  onSearchLocationChange: (coordinates: Coordinates) => void
  onSelect: (id: string) => void
  onLocate: () => void
}

export default function FacilityMap({
  facilities,
  selectedId,
  currentLocation,
  searchLocation,
  walkingRoute,
  locating,
  walkingRanks,
  onSearchLocationChange,
  onSelect,
  onLocate,
}: FacilityMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<kakao.maps.Map | null>(null)
  const draggedLocationRef = useRef<Coordinates | null>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')

  // SDK 로딩 및 지도 생성
  useEffect(() => {
    let cancelled = false
    let observer: ResizeObserver | null = null

    const container = containerRef.current

    loadKakaoMap()
      .then(() => {
        if (cancelled || !container) return

        const map = new window.kakao.maps.Map(container, {
          center: new window.kakao.maps.LatLng(37.5665, 126.978),
          level: 3,
        })

        mapRef.current = map

        observer = new ResizeObserver(() => {
          map.relayout()
        })

        observer.observe(container)
        setReady(true)
      })
      .catch((cause: unknown) => {
        if (cancelled) return

        setError(
          cause instanceof Error
            ? cause.message
            : '지도를 불러오지 못했습니다.',
        )
      })

    return () => {
      cancelled = true
      observer?.disconnect()
      mapRef.current = null
      container?.replaceChildren()
    }
  }, [])
  // 상세 패널이 열려 있으면 지도만 이동하고 검색 기준 유지
  useEffect(() => {
    const map = mapRef.current

    if (!ready || !map) return

    const handleDragEnd = () => {
      // 선택 시설·상세 패널·출발지를 그대로 유지
      if (selectedId !== null) return

      const center = map.getCenter()

      const coordinates: Coordinates = {
        latitude: center.getLat(),
        longitude: center.getLng(),
      }

      draggedLocationRef.current = coordinates
      onSearchLocationChange(coordinates)
    }

    window.kakao.maps.event.addListener(
      map,
      'dragend',
      handleDragEnd,
    )

    return () => {
      window.kakao.maps.event.removeListener(
        map,
        'dragend',
        handleDragEnd,
      )
    }
  }, [ready, selectedId, onSearchLocationChange])

  // 실제 현재 위치 표시. 검색 기준 위치와는 별개.
  useEffect(() => {
    const map = mapRef.current

    if (!ready || !map || !currentLocation) return

    const content = document.createElement('div')
    content.className = 'current-position-marker'
    content.setAttribute('role', 'img')
    content.setAttribute('aria-label', '브라우저에서 확인한 현재 위치')

    const dot = document.createElement('span')
    dot.className = 'current-position-dot'

    content.append(dot)

    const overlay = new window.kakao.maps.CustomOverlay({
      map,
      position: new window.kakao.maps.LatLng(
        currentLocation.latitude,
        currentLocation.longitude,
      ),
      content,
      yAnchor: 0.5,
      zIndex: 30,
    })

    return () => overlay.setMap(null)
  }, [ready, currentLocation])

  // 검색 기준 위치 표시
  useEffect(() => {
    const map = mapRef.current

    if (!ready || !map || !searchLocation) return

    const content = document.createElement('div')
    content.className = 'search-position-marker'
    content.setAttribute('role', 'img')
    content.setAttribute('aria-label', '검색 기준 위치')

    const dot = document.createElement('span')
    dot.className = 'search-position-dot'

    content.append(dot)

    const overlay = new window.kakao.maps.CustomOverlay({
        map,
        position: new window.kakao.maps.LatLng(
            searchLocation.latitude,
            searchLocation.longitude,
        ),
        content,
        xAnchor: 0.5,
        yAnchor: 0.5,
        zIndex: 25,
    })

    return () => overlay.setMap(null)
  }, [ready, searchLocation])

  // 최초 현재 위치 조회 또는 '내 위치' 복귀 시 지도 중심 설정
  useEffect(() => {
    const map = mapRef.current

    if (!ready || !map || !searchLocation) return

    const draggedLocation = draggedLocationRef.current
    draggedLocationRef.current = null

    // 드래그한 위치는 이미 지도 중심이므로 이동·줌 초기화 생략
    if (
      draggedLocation &&
      draggedLocation.latitude === searchLocation.latitude &&
      draggedLocation.longitude === searchLocation.longitude
    ) {
      return
    }

    map.relayout()
    map.setLevel(3)
    map.setCenter(
      new window.kakao.maps.LatLng(
        searchLocation.latitude,
        searchLocation.longitude,
      ),
    )
  }, [ready, searchLocation])

  // 시설 마커
  useEffect(() => {
    const map = mapRef.current

    if (!ready || !map) return

    const overlays: kakao.maps.CustomOverlay[] = []
    const cleanups: (() => void)[] = []

    facilities.forEach((facility) => {
      const walkingRank = walkingRanks[facility.id]
      const isSelected = selectedId === facility.id

      const button = document.createElement('button')

      button.type = 'button'
      button.className = [
        'map-marker',
        'kakao-facility-marker',
        facility.type,
        isSelected ? 'selected' : '',
        walkingRank ? 'is-walking-top' : '',
      ]
        .filter(Boolean)
        .join(' ')

      button.setAttribute(
        'aria-label',
        walkingRank
          ? `${facility.name}, 비교 후보 중 도보 ${walkingRank.rank}순위, ` +
            `예상 ${Math.max(
              1,
              Math.ceil(walkingRank.durationSec / 60),
            )}분`
          : `${facility.name} 상세 보기`,
      )

      button.setAttribute('aria-pressed', String(isSelected))

      // 시설 아이콘
      const symbol = document.createElement('span')
      symbol.className = 'marker-symbol'
      symbol.setAttribute('aria-hidden', 'true')

      const image = document.createElement('img')

      const imageName =
        facility.type === 'aed' ? 'aed_image.jpg' : 'hospital.jpg'

      image.src = `${import.meta.env.BASE_URL}images/${imageName}`
      image.alt = ''
      image.draggable = false
      image.className = 'marker-image'

      symbol.append(image)

      // 시설명: 표시 여부는 기존 hover CSS에서 처리
      const label = document.createElement('span')
      label.className = 'marker-label'
      label.textContent = facility.name

      button.append(symbol, label)

      // 예상 보행시간 상위 3개 순위 배지
      if (walkingRank) {
        const badge = document.createElement('span')

        badge.className = 'map-walking-rank'
        badge.textContent = String(walkingRank.rank)
        badge.setAttribute('aria-hidden', 'true')

        button.append(badge)
      }

      // 마커 선택
      const handleClick = () => onSelect(facility.id)

      button.addEventListener('click', handleClick)

      cleanups.push(() => {
        button.removeEventListener('click', handleClick)
      })

      const overlay = new window.kakao.maps.CustomOverlay({
        map,
        position: new window.kakao.maps.LatLng(
          facility.latitude,
          facility.longitude,
        ),
        content: button,
        clickable: true,
        yAnchor: 1,
        zIndex: isSelected ? 40 : walkingRank ? 20 : 10,
      })

      overlays.push(overlay)
    })

    return () => {
      cleanups.forEach((cleanup) => cleanup())
      overlays.forEach((overlay) => overlay.setMap(null))
    }
  }, [
    ready,
    facilities,
    selectedId,
    onSelect,
    walkingRanks,
  ])
  // 선택한 시설로 이동
  useEffect(() => {
    const map = mapRef.current
    const container = containerRef.current

    if (!ready || !map || !container || !selectedId ) {
      return
    }

    const selected = facilities.find(
      (facility) => facility.id === selectedId,
    )

    if (!selected) return

    map.setCenter(
      new window.kakao.maps.LatLng(
        selected.latitude,
        selected.longitude,
      ),
    )

    if (container.clientWidth > 700) {
      map.panBy(-190, 0)
    }
  }, [ready, selectedId, facilities])

  
  // 도보 경로선 표시
useEffect(() => {
  const map = mapRef.current
  const container = containerRef.current

  if (!ready || !map || !container || !walkingRoute ) {
    return
  }

  const bounds = new window.kakao.maps.LatLngBounds()

  const lines = walkingRoute.segments.map((segment) => {
    const path = segment.map(([longitude, latitude]) => {
      const point = new window.kakao.maps.LatLng(
        latitude,
        longitude,
      )

      bounds.extend(point)
      return point
    })

    return new window.kakao.maps.Polyline({
      map,
      path,
      strokeWeight: 6,
      strokeColor: '#327ce0',
      strokeOpacity: 0.9,
      strokeStyle: 'solid',
      zIndex: 5,
    })
  })

  // 목록·상세 패널에 경로가 가리지 않도록 여백 확보
  if (container.clientWidth > 1000) {
    map.setBounds(bounds, 80, 380, 80, 410)
  } else if (container.clientWidth > 700) {
    map.setBounds(bounds, 80, 50, 80, 410)
  } else {
    map.setBounds(bounds, 110, 30, 35, 30)
  }

  return () => {
    lines.forEach((line) => line.setMap(null))
  }
}, [ready, walkingRoute])

    return (
    <>
      <div
        ref={containerRef}
        className="kakao-map-container"
        role="region"
        aria-label="내 주변 시설 지도"
      />
      {ready && selectedId === null && (
        <div className="map-center-target" aria-hidden="true">
          <span className="map-center-target-dot" />
        </div>
      )}

      {!ready && (
        <div className="map-load-state" role="status">
          {error || '지도를 불러오는 중입니다…'}
        </div>
      )}

      <button
        type="button"
        className="location-button"
        aria-label="내 위치로 돌아가서 검색"
        disabled={!ready || locating}
        onClick={onLocate}
      >
        <Icon name="location" size={23} />
      </button>
    </>
  )

}