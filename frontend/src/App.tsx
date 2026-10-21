import { useCallback, useState } from 'react'
import Header from './components/Header'
import FacilityMap from './components/FacilityMap'
import FacilityExplorer from './components/FacilityExplorer'
import FacilityDetail from './components/FacilityDetail'
import Toast from './components/Toast'
import { useGeolocation } from './hooks/useGeolocation'
import { useWalkingRoute } from './hooks/useWalkingRoute'
import { useNearbyFacilities } from './hooks/useNearbyFacilities'
import { useWalkingRanking } from './hooks/useWalkingRanking'
import type { FacilityFilter } from './types/facility'
import type { Coordinates } from './types/location'
import './App.css'

const SEARCH_RADIUS_BY_FILTER: Record<FacilityFilter, number> = {
  all: 500,
  aed: 500,
  emergency_room: 15000,
}

function App() {
  const [filter, setFilter] = useState<FacilityFilter>('all')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [message, setMessage] = useState('')

  const [customSearchLocation, setCustomSearchLocation] =
    useState<Coordinates | null>(null)

  const location = useGeolocation()

  // 최초에는 현재 위치, 지도 드래그 후에는 선택한 위치 사용
  const searchLocation =
    customSearchLocation ?? location.coordinates

  const handleSearchLocationChange = useCallback(
    (coordinates: Coordinates) => {
      setCustomSearchLocation(coordinates)
      setSelectedId(null)
      setMessage('')
    },
    [],
  )

  function useCurrentLocation() {
    setCustomSearchLocation(null)
    setSelectedId(null)
    setMessage('')
    location.refresh()
  }

  const searchRadiusM = SEARCH_RADIUS_BY_FILTER[filter]

  const nearby = useNearbyFacilities(
    searchLocation,
    filter,
    searchRadiusM,
  )

  const visibleFacilities = nearby.facilities.filter((facility) =>
    `${facility.name} ${facility.address}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  )

  // 직선거리순 목록에서 최대 5곳을 경로 비교 후보로 선정
  const comparisonCandidates = visibleFacilities.slice(0, 5)

  // AED는 도보, 응급실은 차량 이동시간 비교
  const ranking = useWalkingRanking(
    searchLocation,
    comparisonCandidates,
    filter !== 'all',
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
    selectedFacility,
  )

  // 비교 과정에서 계산한 경로를 상세 화면에서도 재사용
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


  return (
    <main className="app-shell">
      <FacilityMap
        facilities={visibleFacilities}
        selectedId={selectedId}
        walkingRoute={displayedRoute}
        walkingRanks={walkingRanks}
        currentLocation={location.coordinates}
        searchLocation={searchLocation}
        locating={location.status === 'loading'}
        onSelect={setSelectedId}
        onLocate={useCurrentLocation}
        onSearchLocationChange={handleSearchLocationChange}
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
          searchLocation !== null &&
          filter !== 'all' &&
          nearby.status === 'success' &&
          comparisonCandidates.length > 0
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