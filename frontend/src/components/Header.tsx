export default function Header() {
  return (
    <header className="topbar">
      <a className="brand" href="./" aria-label="LifeTime 처음 화면">
        <span className="brand-symbol">+</span>
        <span>
          LifeTime<span className="brand-dot">.</span>
        </span>
      </a>

      <span className="preview-label">
        <span />
        가상 데이터 미리보기
      </span>
    </header>
  )
}