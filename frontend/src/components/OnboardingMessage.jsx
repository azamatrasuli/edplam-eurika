import { OnboardingButtons } from './OnboardingButtons'
import { OnboardingForm } from './OnboardingForm'
import { ProfileCard } from './ProfileCard'

export function OnboardingMessage({ message, onButtonClick, onFormSubmit }) {
  if (message.type === 'buttons') {
    return (
      <div>
        {message.content && <p className="text-[15px] leading-normal">{message.content}</p>}
        <OnboardingButtons
          buttons={message.buttons}
          disabled={message.disabled}
          onSelect={onButtonClick}
        />
      </div>
    )
  }

  if (message.type === 'form') {
    return (
      <div>
        {message.content && <p className="text-[15px] leading-normal mb-1">{message.content}</p>}
        <OnboardingForm
          formType={message.formType}
          disabled={message.disabled}
          onSubmit={onFormSubmit}
          isExisting={true}
        />
      </div>
    )
  }

  if (message.type === 'card') {
    return (
      <div>
        {message.content && <p className="text-[15px] leading-normal">{message.content}</p>}
        <ProfileCard data={message.cardData} />
      </div>
    )
  }

  // Default: plain text (shouldn't reach here, handled by ChatWindow)
  return <p className="text-[15px] leading-normal">{message.content}</p>
}
