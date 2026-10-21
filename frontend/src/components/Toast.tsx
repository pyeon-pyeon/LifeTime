import Icon from './Icon'

type ToastProps = {
  message: string
  onClose: () => void
}

export default function Toast({ message, onClose }: ToastProps) {
  if (!message) return null

  return (
    <div className="toast" role="status">
      <span>{message}</span>

      <button
        type="button"
        className="icon-button"
        aria-label="알림 닫기"
        onClick={onClose}
      >
        <Icon name="close" size={16} />
      </button>
    </div>
  )
}