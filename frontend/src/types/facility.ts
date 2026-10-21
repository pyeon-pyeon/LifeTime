export type FacilityType = 'aed' | 'emergency_room'

export type FacilityFilter = 'all' | FacilityType

export type Facility = {
  id: string
  type: FacilityType
  name: string
  address: string
  detail: string
  hours: string
  latitude: number
  longitude: number
}