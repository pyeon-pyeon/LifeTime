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
  editingLocation: boolean
  locating: boolean
  walkingRanks: WalkingRanks
  onSelect: (id: string) => void
  onLocate: () => void
  onConfirmLocation: (coordinates: Coordinates) => void
  onCancelEdit: () => void
}

export default function FacilityMap({
  facilities,
  selectedId,
  currentLocation,
  searchLocation,
  walkingRoute,
  editingLocation,
  locating,
  walkingRanks,
  onSelect,
  onLocate,
  onConfirmLocation,
  onCancelEdit,
}: FacilityMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<kakao.maps.Map | null>(null)

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

    if (!ready || !map || !searchLocation || editingLocation) return

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
  }, [ready, searchLocation, editingLocation])

  // 위치 수정 진입·취소·확정 시 지도 중심 설정
  useEffect(() => {
    const map = mapRef.current
    const container = containerRef.current

    if (!ready || !map || !container) return

    // 패널 숨김으로 지도 크기가 변경된 뒤 크기 재계산
    map.relayout()

    if (searchLocation) {
      map.setCenter(
        new window.kakao.maps.LatLng(
          searchLocation.latitude,
          searchLocation.longitude,
        ),
      )
    }

    // 수정 중에는 중앙 핀과 지도 중심을 정확하게 일치시킴
    if (!editingLocation && searchLocation && container.clientWidth > 700) {
      map.panBy(-190, 0)
    }
  }, [ready, searchLocation, editingLocation])

  // 시설 마커
  useEffect(() => {
    const map = mapRef.current

    if (!ready || !map || editingLocation) return

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
    editingLocation,
    onSelect,
    walkingRanks,
  ])
  // 선택한 시설로 이동
  useEffect(() => {
    const map = mapRef.current
    const container = containerRef.current

    if (!ready || !map || !container || !selectedId || editingLocation) {
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
  }, [ready, selectedId, facilities, editingLocation])

  function confirmLocation() {
    const map = mapRef.current
    if (!map) return

    const center = map.getCenter()

    onConfirmLocation({
      latitude: center.getLat(),
      longitude: center.getLng(),
    })
  }
  // 도보 경로선 표시
useEffect(() => {
  const map = mapRef.current
  const container = containerRef.current

  if (!ready || !map || !container || !walkingRoute || editingLocation) {
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
}, [ready, walkingRoute, editingLocation])

  return (
    <>
      <div
        ref={containerRef}
        className={`kakao-map-container ${
          editingLocation ? 'is-editing-location' : ''
        }`}
        role="region"
        aria-label="내 주변 시설 지도"
      />

      {!ready && (
        <div className="map-load-state" role="status">
          {error || '지도를 불러오는 중입니다…'}
        </div>
      )}

      {editingLocation && ready && (
        <>
          <div className="location-edit-pin" aria-hidden="true">
            <div className="location-edit-target" aria-hidden="true">
                <span className="location-edit-target-dot" />
            </div>
          </div>

          <div className="location-edit-hint" role="status">
            <span className="location-edit-hint-dot" />
            지도를 움직여 위치를 맞춰주세요
          </div>

          <section
            className="location-edit-panel"
            aria-label="검색 위치 설정"
          >
            <div className="location-edit-copy">
                <span className="location-edit-caption">SEARCH LOCATION</span>
                <strong>어디에서 찾을까요?</strong>
            </div>

            <div className="location-edit-actions">
                <button
                type="button"
                className="location-edit-cancel"
                onClick={onCancelEdit}
                >
                취소
                </button>

                <button
                type="button"
                className="location-edit-confirm"
                onClick={confirmLocation}
                >
                이 위치로 설정
                <Icon name="arrow" size={17} />
                </button>
            </div>
          </section>
        </>
      )}

      {!editingLocation && (
        <button
          type="button"
          className="location-button"
          aria-label="현재 위치 다시 확인 및 검색"
          disabled={!ready || locating}
          onClick={onLocate}
        >
          <Icon name="location" size={23} />
        </button>
      )}
    </>
  )
}