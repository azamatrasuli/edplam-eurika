import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { checkProfile, verifyOnboarding } from '../api/client'

const STEPS = {
  CHECKING: 'checking',
  CLIENT_TYPE: 'client_type',
  ROLE: 'role',
  DATA: 'data',
  VERIFYING: 'verifying',
  RESULT: 'result',
  COMPLETE: 'complete',
}

function profileStorageKey(actorId) {
  return `eurika_profile_${actorId}`
}

function makeId() {
  return crypto.randomUUID()
}

export function useOnboarding(auth, actorId, actorPhone) {
  const [step, setStep] = useState(STEPS.CHECKING)
  const [messages, setMessages] = useState([])
  const [clientType, setClientType] = useState(null)
  const [userRole, setUserRole] = useState(null)
  const [profileData, setProfileData] = useState(null)
  const [error, setError] = useState('')
  const initDone = useRef(false)

  // Check for existing profile on mount
  useEffect(() => {
    if (!auth || initDone.current) return
    initDone.current = true

    ;(async () => {
      try {
        // Quick localStorage check
        if (actorId) {
          const cached = localStorage.getItem(profileStorageKey(actorId))
          if (cached) {
            try {
              const parsed = JSON.parse(cached)
              if (parsed && parsed.profile_id) {
                // Validate with backend
                const res = await checkProfile(auth)
                if (res.has_profile) {
                  setProfileData(res.profile)
                  setStep(STEPS.COMPLETE)
                  return
                }
                // Backend says no profile — clear stale cache
                localStorage.removeItem(profileStorageKey(actorId))
              }
            } catch {
              localStorage.removeItem(profileStorageKey(actorId))
            }
          }
        }

        // Check backend
        const res = await checkProfile(auth)
        if (res.has_profile) {
          setProfileData(res.profile)
          if (actorId) {
            localStorage.setItem(
              profileStorageKey(actorId),
              JSON.stringify({ profile_id: res.profile.id }),
            )
          }
          setStep(STEPS.COMPLETE)
          return
        }

        // Portal auto-verify: if we already have a phone from JWT
        if (actorPhone) {
          setStep(STEPS.VERIFYING)
          addAssistantMessage('Проверяю ваши данные в системе...')
          const verifyRes = await verifyOnboarding(auth, {
            client_type: 'existing',
            user_role: 'parent',
            phone: actorPhone,
            students: [],
          })
          handleVerifyResult(verifyRes, 'existing')
          return
        }

        // Start onboarding wizard
        setStep(STEPS.CLIENT_TYPE)
        setMessages([
          {
            id: makeId(),
            role: 'assistant',
            content:
              'Здравствуйте! Я Эврика, виртуальный менеджер EdPalm.\nДавайте познакомимся, чтобы я могла помочь максимально точно.',
            type: 'text',
          },
          {
            id: makeId(),
            role: 'assistant',
            content: 'Вы уже учитесь у нас или рассматриваете поступление?',
            type: 'buttons',
            buttons: [
              { id: 'existing', label: 'Уже учусь в EdPalm', value: 'existing' },
              { id: 'new', label: 'Рассматриваю поступление', value: 'new' },
            ],
            disabled: false,
          },
        ])
      } catch (e) {
        setError(e.message)
        // Fall through to onboarding on error
        setStep(STEPS.CLIENT_TYPE)
        setMessages([
          {
            id: makeId(),
            role: 'assistant',
            content:
              'Здравствуйте! Я Эврика, виртуальный менеджер EdPalm.\nДавайте познакомимся, чтобы я могла помочь максимально точно.',
            type: 'text',
          },
          {
            id: makeId(),
            role: 'assistant',
            content: 'Вы уже учитесь у нас или рассматриваете поступление?',
            type: 'buttons',
            buttons: [
              { id: 'existing', label: 'Уже учусь в EdPalm', value: 'existing' },
              { id: 'new', label: 'Рассматриваю поступление', value: 'new' },
            ],
            disabled: false,
          },
        ])
      }
    })()
  }, [auth, actorId, actorPhone])

  function addAssistantMessage(content, extra = {}) {
    setMessages((prev) => [...prev, { id: makeId(), role: 'assistant', content, type: 'text', ...extra }])
  }

  function addUserMessage(content) {
    setMessages((prev) => [...prev, { id: makeId(), role: 'user', content, type: 'text' }])
  }

  function disableLastButtons() {
    setMessages((prev) =>
      prev.map((m, i) => (i === prev.length - 1 && m.type === 'buttons' ? { ...m, disabled: true } : m)),
    )
  }

  // Handle button click from any step
  const handleButtonClick = useCallback(
    (value) => {
      if (step === STEPS.CLIENT_TYPE) {
        disableLastButtons()
        setClientType(value)
        addUserMessage(value === 'existing' ? 'Уже учусь в EdPalm' : 'Рассматриваю поступление')

        // Move to role step
        setStep(STEPS.ROLE)
        setTimeout(() => {
          setMessages((prev) => [
            ...prev,
            {
              id: makeId(),
              role: 'assistant',
              content: 'Вы зашли как родитель или как ученик?',
              type: 'buttons',
              buttons: [
                { id: 'parent', label: 'Я родитель', value: 'parent' },
                { id: 'student', label: 'Я ученик', value: 'student' },
              ],
              disabled: false,
            },
          ])
        }, 400)
      } else if (step === STEPS.ROLE) {
        disableLastButtons()
        setUserRole(value)
        addUserMessage(value === 'parent' ? 'Я родитель' : 'Я ученик')

        // Move to data collection step
        setStep(STEPS.DATA)
        const currentClientType = clientType // capture from closure
        setTimeout(() => {
          const isParent = value === 'parent'
          const isExisting = currentClientType === 'existing'

          let formPrompt
          if (isParent && isExisting) {
            formPrompt = 'Для идентификации в системе укажите данные ребёнка.'
          } else if (isParent && !isExisting) {
            formPrompt = 'Расскажите о ребёнке — это поможет подобрать программу.'
          } else if (!isParent && isExisting) {
            formPrompt = 'Укажите ваши данные для идентификации в системе.'
          } else {
            formPrompt = 'Расскажите о себе — это поможет подобрать программу.'
          }

          setMessages((prev) => [
            ...prev,
            {
              id: makeId(),
              role: 'assistant',
              content: formPrompt,
              type: 'form',
              formType: isParent ? 'parent' : 'student',
              disabled: false,
            },
          ])
        }, 400)
      } else if (step === STEPS.RESULT) {
        // Handle result-step buttons (retry, escalate, confirm)
        if (value === 'retry') {
          setStep(STEPS.DATA)
          setMessages((prev) => {
            const filtered = prev.map((m) => (m.type === 'buttons' && !m.disabled ? { ...m, disabled: true } : m))
            return [
              ...filtered,
              {
                id: makeId(),
                role: 'assistant',
                content: userRole === 'parent'
                  ? 'Давайте попробуем ещё раз. Укажите данные ребёнка.'
                  : 'Давайте попробуем ещё раз. Укажите ваши данные.',
                type: 'form',
                formType: userRole === 'parent' ? 'parent' : 'student',
                disabled: false,
              },
            ]
          })
        } else if (value === 'escalate') {
          disableLastButtons()
          addUserMessage('Подключить менеджера')
          finishOnboarding(null)
        } else if (value === 'confirm_existing') {
          disableLastButtons()
          addUserMessage('Да, я действующий ученик')
          finishOnboarding(profileData)
        } else if (value === 'new_anyway') {
          disableLastButtons()
          addUserMessage('Нет, новая заявка')
          finishOnboarding(profileData)
        }
      }
    },
    [step, clientType, userRole, profileData],
  )

  // Handle form submission
  const handleFormSubmit = useCallback(
    async (formData) => {
      // Disable the form
      setMessages((prev) => prev.map((m) => (m.type === 'form' && !m.disabled ? { ...m, disabled: true } : m)))

      // Show user's input as a message
      if (formData.students && formData.students.length > 0) {
        const studentsSummary = formData.students
          .map((s) => `${s.fio}, ${s.grade} класс`)
          .join('\n')
        addUserMessage(`${studentsSummary}\nТелефон: ${formData.phone}`)
      } else {
        addUserMessage(`${formData.fio}, ${formData.grade} класс\nТелефон: ${formData.phone}`)
      }

      // Start verification
      setStep(STEPS.VERIFYING)
      setTimeout(() => addAssistantMessage('Проверяю данные в системе...'), 300)

      try {
        const payload = {
          client_type: clientType,
          user_role: userRole,
          phone: formData.phone,
          students: formData.students || [],
          fio: formData.fio || null,
          grade: formData.grade || null,
        }
        const res = await verifyOnboarding(auth, payload)
        handleVerifyResult(res, clientType)
      } catch (e) {
        setError(e.message)
        addAssistantMessage('Не удалось проверить данные автоматически. Менеджер проверит позже.')
        finishOnboarding(null)
      }
    },
    [auth, clientType, userRole],
  )

  function handleVerifyResult(res, clType) {
    setStep(STEPS.RESULT)

    if (res.status === 'found') {
      // Found in DMS — show profile card
      setProfileData(res)
      setMessages((prev) => [
        ...prev.filter((m) => m.content !== 'Проверяю данные в системе...' && m.content !== 'Проверяю ваши данные в системе...'),
        {
          id: makeId(),
          role: 'assistant',
          content: 'Нашла вас в системе!',
          type: 'card',
          cardData: res.dms_data,
        },
        {
          id: makeId(),
          role: 'assistant',
          content: 'Всё верно? Чем могу помочь?',
          type: 'text',
        },
      ])
      // Auto-finish after showing card
      setTimeout(() => finishOnboarding(res), 800)
    } else if (res.status === 'not_found') {
      setMessages((prev) => [
        ...prev.filter((m) => m.content !== 'Проверяю данные в системе...' && m.content !== 'Проверяю ваши данные в системе...'),
        {
          id: makeId(),
          role: 'assistant',
          content:
            'Не удалось найти ученика с такими данными в системе.\nВозможно, ФИО указаны не так, как в личном кабинете, или используется другой номер телефона.',
          type: 'text',
        },
        {
          id: makeId(),
          role: 'assistant',
          content: 'Что хотите сделать?',
          type: 'buttons',
          buttons: [
            { id: 'retry', label: 'Ввести заново', value: 'retry' },
            { id: 'escalate', label: 'Подключить менеджера', value: 'escalate' },
          ],
          disabled: false,
        },
      ])
    } else if (res.status === 'unexpected_found') {
      setProfileData(res)
      setMessages((prev) => [
        ...prev.filter((m) => m.content !== 'Проверяю данные в системе...' && m.content !== 'Проверяю ваши данные в системе...'),
        {
          id: makeId(),
          role: 'assistant',
          content: 'Похоже, вы уже зарегистрированы в нашей системе!',
          type: 'card',
          cardData: res.dms_data,
        },
        {
          id: makeId(),
          role: 'assistant',
          content: '',
          type: 'buttons',
          buttons: [
            { id: 'confirm_existing', label: 'Да, я действующий ученик', value: 'confirm_existing' },
            { id: 'new_anyway', label: 'Нет, новая заявка', value: 'new_anyway' },
          ],
          disabled: false,
        },
      ])
    } else {
      // new_lead
      setProfileData(res)
      setMessages((prev) => [
        ...prev.filter((m) => m.content !== 'Проверяю данные в системе...' && m.content !== 'Проверяю ваши данные в системе...'),
        {
          id: makeId(),
          role: 'assistant',
          content: 'Спасибо! Записала ваши данные.\nДавайте подберём подходящую программу обучения.',
          type: 'text',
        },
      ])
      setTimeout(() => finishOnboarding(res), 600)
    }
  }

  function finishOnboarding(data) {
    setProfileData(data)
    if (actorId && data) {
      localStorage.setItem(
        profileStorageKey(actorId),
        JSON.stringify({ profile_id: data.profile_id || data.id || '' }),
      )
    }
    setStep(STEPS.COMPLETE)
  }

  const isComplete = step === STEPS.COMPLETE
  const isChecking = step === STEPS.CHECKING

  return useMemo(
    () => ({
      step,
      messages,
      isComplete,
      isChecking,
      profileData,
      error,
      handleButtonClick,
      handleFormSubmit,
    }),
    [step, messages, isComplete, isChecking, profileData, error, handleButtonClick, handleFormSubmit],
  )
}
