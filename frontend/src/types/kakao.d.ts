/// <reference types="kakao.maps.d.ts" />

interface Window {
  kakao: typeof kakao
}

interface ImportMetaEnv {
  readonly VITE_KAKAO_MAP_APP_KEY?: string
}