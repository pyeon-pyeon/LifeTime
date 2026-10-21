import { useState } from 'react'
import Header from './components/Header'
import FacilityMap from './components/FacilityMap'
import FacilityExplorer from './components/FacilityExplorer'
import FacilityDetail from './components/FacilityDetail'
import Toast from './components/Toast'
import { mockFacilities } from './mocks/facilities'
import { useGeolocation } from './hooks/useGeolocation'
import { distanceMeters } from './utils/distance'
import type { FacilityFilter } from './types/facility'
import './App.css'
import type { Coordinates } from './types/location'
import { useWalkingRoute } from './hooks/useWalkingRoute'

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

  const nearbyFacilities = searchLocation
    ? mockFacilities
        .map((facility) => ({
          ...facility,
          straightDistanceM: distanceMeters(searchLocation, facility),
        }))
        .filter(
          (facility) => facility.straightDistanceM <= SEARCH_RADIUS_M,
        )
        .sort(
          (a, b) => a.straightDistanceM - b.straightDistanceM,
        )
    : []

  const visibleFacilities = nearbyFacilities.filter((facility) => {
    const matchesType = filter === 'all' || facility.type === filter

    const matchesQuery = `${facility.name} ${facility.address}`
      .toLowerCase()
      .includes(query.trim().toLowerCase())

    return matchesType && matchesQuery
  })

  const selectedFacility = visibleFacilities.find(
    (facility) => facility.id === selectedId,
  )
  const walking = useWalkingRoute(
    searchLocation,
    editingLocation ? undefined : selectedFacility,
  )

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
        walkingRoute={walking.route}
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
        onFilterChange={handleFilterChange}
        onQueryChange={handleQueryChange}
        onSelect={setSelectedId}
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
          walkingRoute={walking.route}
          routeLoading={walking.loading}
          routeError={walking.error}
          onClose={() => setSelectedId(null)}
          onRouteRequest={() => {
            if (!searchLocation) {
              setMessage('먼저 현재 위치 또는 검색 위치를 설정해 주세요.')
              return
            }

            if (!walking.loading) {
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