import { useState } from 'react'

const GRADES = Array.from({ length: 11 }, (_, i) => i + 1)

function StudentFields({ index, student, onChange, onRemove, showRemove, isExisting }) {
  return (
    <div className="space-y-2.5">
      {index > 0 && (
        <div className="flex items-center justify-between pt-2 border-t border-input-area-border">
          <span className="text-[13px] text-fg-muted font-medium">Ученик {index + 1}</span>
          {showRemove && (
            <button
              type="button"
              onClick={onRemove}
              className="text-[12px] text-error hover:underline"
            >
              Удалить
            </button>
          )}
        </div>
      )}
      {index === 0 && <span className="text-[13px] text-fg-muted font-medium block">Ученик 1</span>}
      <input
        type="text"
        placeholder={isExisting ? 'ФИО ученика (как в школе)' : 'ФИО ребёнка'}
        value={student.fio}
        onChange={(e) => onChange({ ...student, fio: e.target.value })}
        className="onboarding-input"
      />
      <select
        value={student.grade || ''}
        onChange={(e) => onChange({ ...student, grade: Number(e.target.value) })}
        className="onboarding-input"
      >
        <option value="" disabled>
          {isExisting ? 'Класс' : 'Желаемый класс'}
        </option>
        {GRADES.map((g) => (
          <option key={g} value={g}>
            {g} класс
          </option>
        ))}
      </select>
    </div>
  )
}

export function OnboardingForm({ formType, disabled, onSubmit, isExisting }) {
  const isParent = formType === 'parent'
  const [students, setStudents] = useState([{ fio: '', grade: null }])
  const [fio, setFio] = useState('')
  const [grade, setGrade] = useState(null)
  const [phone, setPhone] = useState('')
  const [errors, setErrors] = useState({})

  function formatPhone(value) {
    // Keep only digits and leading +
    let digits = value.replace(/[^\d+]/g, '')
    if (digits.startsWith('+')) {
      digits = '+' + digits.slice(1).replace(/\+/g, '')
    }
    // Auto-prepend +7 for Russian numbers
    if (digits.startsWith('8') && digits.length > 1) {
      digits = '+7' + digits.slice(1)
    }
    if (digits.length > 0 && !digits.startsWith('+')) {
      digits = '+' + digits
    }
    return digits.slice(0, 16)
  }

  function handlePhoneChange(e) {
    setPhone(formatPhone(e.target.value))
  }

  function updateStudent(index, data) {
    setStudents((prev) => prev.map((s, i) => (i === index ? data : s)))
  }

  function addStudent() {
    if (students.length < 5) {
      setStudents((prev) => [...prev, { fio: '', grade: null }])
    }
  }

  function removeStudent(index) {
    setStudents((prev) => prev.filter((_, i) => i !== index))
  }

  function validate() {
    const errs = {}
    const phoneDigits = phone.replace(/\D/g, '')

    if (phoneDigits.length < 10) {
      errs.phone = 'Укажите корректный номер телефона'
    }

    if (isParent) {
      students.forEach((s, i) => {
        if (!s.fio || s.fio.trim().length < 2) errs[`student_${i}_fio`] = true
        if (!s.grade) errs[`student_${i}_grade`] = true
      })
    } else {
      if (!fio || fio.trim().length < 2) errs.fio = 'Укажите ФИО'
      if (!grade) errs.grade = 'Выберите класс'
    }
    return errs
  }

  function handleSubmit(e) {
    e.preventDefault()
    const errs = validate()
    setErrors(errs)
    if (Object.keys(errs).length > 0) return

    if (isParent) {
      onSubmit({ students, phone })
    } else {
      onSubmit({ fio, grade, phone })
    }
  }

  if (disabled) {
    return (
      <div className="mt-2 px-3 py-3 rounded-xl bg-surface-alt/50 text-fg-muted text-[13px]">
        Данные отправлены
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 space-y-3 max-w-[320px] bg-elevated/50 rounded-2xl p-4 border border-border-subtle">
      {isParent ? (
        <>
          {students.map((student, i) => (
            <StudentFields
              key={i}
              index={i}
              student={student}
              onChange={(data) => updateStudent(i, data)}
              onRemove={() => removeStudent(i)}
              showRemove={students.length > 1}
              isExisting={isExisting}
            />
          ))}
          {students.length < 5 && (
            <button
              type="button"
              onClick={addStudent}
              className="text-brand text-[13px] font-medium hover:underline flex items-center gap-1"
            >
              <span className="text-[16px] leading-none">+</span> Добавить ещё ученика
            </button>
          )}
        </>
      ) : (
        <div className="space-y-2.5">
          <input
            type="text"
            placeholder="Ваше ФИО"
            value={fio}
            onChange={(e) => setFio(e.target.value)}
            className={`onboarding-input ${errors.fio ? 'border-error' : ''}`}
          />
          <select
            value={grade || ''}
            onChange={(e) => setGrade(Number(e.target.value))}
            className={`onboarding-input ${errors.grade ? 'border-error' : ''}`}
          >
            <option value="" disabled>
              {isExisting ? 'Класс' : 'Класс поступления'}
            </option>
            {GRADES.map((g) => (
              <option key={g} value={g}>
                {g} класс
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="space-y-1">
        <input
          type="tel"
          placeholder="+7 999 123-45-67"
          value={phone}
          onChange={handlePhoneChange}
          className={`onboarding-input ${errors.phone ? 'border-error' : ''}`}
        />
        {errors.phone && <p className="text-[12px] text-error">{errors.phone}</p>}
      </div>

      <button
        type="submit"
        className="
          w-full py-2.5 rounded-2xl text-[14px] font-medium
          bg-brand text-white
          transition-all duration-200 ease-out
          hover:bg-brand-hover active:scale-[0.97]
          shadow-sm hover:shadow-md
          flex items-center justify-center gap-1.5
        "
      >
        Продолжить
        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="5" y1="12" x2="19" y2="12" />
          <polyline points="12 5 19 12 12 19" />
        </svg>
      </button>
    </form>
  )
}
