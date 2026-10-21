import { useState } from 'react'
import Header from './components/Header'
import FacilityMap from './components/FacilityMap'
import FacilityExplorer from './components/FacilityExplorer'
import FacilityDetail from './components/FacilityDetail'
import Toast from './components/Toast'
import { useGeolocation } from './hooks/useGeolocation'
import type { FacilityFilter } from './types/facility'
import './App.css'
import type { Coordinates } from './types/location'
import { useWalkingRoute } from './hooks/useWalkingRoute'
import { useNearbyFacilities } from './hooks/useNearbyFacilities'
import { useWalkingRanking } from './hooks/useWalkingRanking'


const SEARCH_RADIUS_M = 3000

function App() {
  const [filter, setFilter] = useState<FacilityFilter>('all')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [message, setMessage] = useState('')

  const location = useGeolocation()
  const [customSearchLocation, setCustomSearchLocation] =
  useState<Coordinates | null>(null)

  const [editingLocation, setEditingLocation] = useState(false)

  // 수동 설정이 있으면 그 위치, 없으면 현재 위치 사용
  const searchLocation = customSearchLocation ?? location.coordinates

  function confirmSearchLocation(coordinates: Coordinates) {
    setCustomSearchLocation(coordinates)
    setEditingLocation(false)
    setSelectedId(null)
    setMessage('선택한 위치를 기준으로 주변 시설을 검색합니다.')
  }

  function useCurrentLocation() {
    setCustomSearchLocation(null)
    setEditingLocation(false)
    setSelectedId(null)
    location.refresh()
  }

  const nearby = useNearbyFacilities(
    searchLocation,
    filter,
    SEARCH_RADIUS_M,
  )

  const visibleFacilities = nearby.facilities.filter((facility) =>
    `${facility.name} ${facility.address}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  )

  // nearby.facilities는 앞서 직선거리순으로 정렬한 API 결과
  // 검색어로 좁힌 결과 중 최대 5개를 비교
  const comparisonCandidates = visibleFacilities.slice(0, 5)

  const ranking = useWalkingRanking(
    searchLocation,
    comparisonCandidates,
    filter !== 'all' && !editingLocation,
  )

  const topThree = ranking.results.slice(0, 3)

  const walkingRanks = Object.fromEntries(
    topThree.map((item, index) => [
      item.facilityId,
      {
        rank: index + 1,
        durationSec: item.route.durationSec,
      },
    ]),
  )

  const selectedFacility = visibleFacilities.find(
    (facility) => facility.id === selectedId,
  )
  const walking = useWalkingRoute(
    searchLocation,
    editingLocation ? undefined : selectedFacility,
  )
  // 비교 과정에서 계산한 경로는 상세 화면에서도 재사용
  const comparedRoute = ranking.results.find(
    (item) => item.facilityId === selectedFacility?.id,
  )?.route

  const displayedRoute = comparedRoute ?? walking.route

  function handleFilterChange(nextFilter: FacilityFilter) {
    setFilter(nextFilter)
    setSelectedId(null)
  }

  function handleQueryChange(nextQuery: string) {
    setQuery(nextQuery)
    setSelectedId(null)
  }

  const locationDescription = customSearchLocation
    ? '직접 선택한 위치 기준 · 반경 3km'
    : location.status === 'loading'
      ? '현재 위치를 확인하고 있습니다.'
      : location.status === 'error'
        ? location.error ?? '현재 위치를 확인하지 못했습니다.'
        : `현재 위치 기준 반경 3km · 위치 정확도 약 ${Math.round(
            location.accuracy ?? 0,
          )}m`

  return (
    <main className={`app-shell ${editingLocation ? 'editing-location' : ''}`}>
      <FacilityMap
        facilities={visibleFacilities}
        selectedId={selectedId}
        walkingRoute={displayedRoute}
        walkingRanks={walkingRanks}
        currentLocation={location.coordinates}
        searchLocation={searchLocation}
        editingLocation={editingLocation}
        locating={location.status === 'loading'}
        onSelect={setSelectedId}
        onLocate={useCurrentLocation}
        onConfirmLocation={confirmSearchLocation}
        onCancelEdit={() => setEditingLocation(false)}
      />

      <Header />

      <FacilityExplorer
        facilities={visibleFacilities}
        filter={filter}
        query={query}
        selectedId={selectedId}
        loadStatus={nearby.status}
        loadError={nearby.error}
        onRetry={nearby.retry}
        onFilterChange={handleFilterChange}
        onQueryChange={handleQueryChange}
        onSelect={setSelectedId}
        walkingRanks={walkingRanks}
        comparisonEnabled={
          filter !== 'all' &&
          nearby.status === 'success' &&
          comparisonCandidates.length > 0 &&
          !editingLocation
        }
        comparisonLoading={ranking.loading}
        comparisonDone={ranking.done}
        comparisonCompleted={ranking.completed}
        comparisonTotal={comparisonCandidates.length}
        comparisonSuccessCount={ranking.results.length}
        comparisonFailedCount={ranking.failedIds.length}
        onCompare={() => {
          if (!walking.loading) {
            void ranking.compare()
          }
        }}
      />

      {!editingLocation && (
        <div
          className={`location-status ${
            !customSearchLocation && location.status === 'error'
              ? 'is-error'
              : ''
          }`}
          role="status"
        >
          <span>{locationDescription}</span>

          <button
            type="button"
            onClick={() => {
              setSelectedId(null)
              setEditingLocation(true)
            }}
          >
            위치 수정
          </button>

          {customSearchLocation && (
            <button
              type="button"
              onClick={useCurrentLocation}
            >
              현재 위치 사용
            </button>
          )}

          {!customSearchLocation && location.status === 'error' && (
            <button type="button" onClick={useCurrentLocation}>
              다시 시도
            </button>
          )}
        </div>
      )}

      {selectedFacility && (
        <FacilityDetail
          facility={selectedFacility}
          walkingRoute={displayedRoute}
          routeLoading={!comparedRoute && walking.loading}
          routeError={comparedRoute ? null : walking.error}
          onClose={() => setSelectedId(null)}
          onRouteRequest={() => {
            if (!searchLocation) {
              setMessage('먼저 검색 위치를 설정해 주세요.')
              return
            }

            if (comparedRoute) {
              const travelMode =
                selectedFacility.type === 'aed' ? '도보' : '차량'

              setMessage(
                `비교할 때 계산한 ${travelMode} 경로를 표시하고 있습니다.`,
              )
              return
            }

            if (!walking.loading && !ranking.loading) {
              void walking.requestRoute()
            }
          }}
        />
      )}

      <Toast
        message={message}
        onClose={() => setMessage('')}
      />
    </main>
  )
}

export default App