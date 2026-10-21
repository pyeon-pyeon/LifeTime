import type { Coordinates } from '../types/location'

export function distanceMeters(
  origin: Coordinates,
  destination: Coordinates,
): number {
  const radians = (degrees: number) => degrees * Math.PI / 180

  const latitudeDiff = radians(
    destination.latitude - origin.latitude,
  )

  const longitudeDiff = radians(
    destination.longitude - origin.longitude,
  )

  const value =
    Math.sin(latitudeDiff / 2) ** 2 +
    Math.cos(radians(origin.latitude)) *
      Math.cos(radians(destination.latitude)) *
      Math.sin(longitudeDiff / 2) ** 2

  const clamped = Math.min(1, Math.max(0, value))

  return 6371000 * 2 * Math.atan2(
    Math.sqrt(clamped),
    Math.sqrt(1 - clamped),
  )
}