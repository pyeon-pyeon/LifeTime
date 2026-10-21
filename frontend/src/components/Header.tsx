export default function Header() {
  return (
    <header className="topbar">
      <a className="brand" href="./" aria-label="LifeTime 처음 화면">
        <img
          className="brand-logo"
          src={`${import.meta.env.BASE_URL}images/logo.png`}
          alt=""
          width={36}
          height={36}
        />

        <span>
          LifeTime
        </span>
      </a>

      <a
        className="emergency-call-button"
        href="tel:119"
        aria-label="119에 전화하기"
      >
        119 전화
      </a>
    </header>
  )
}