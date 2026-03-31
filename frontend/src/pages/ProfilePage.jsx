import { useMemo, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { buildAuthPayload } from '../lib/authContext'
import { useProfile } from '../hooks/useProfile'

const TABS = [
  { id: 'profile', label: 'Профиль' },
  { id: 'privacy', label: 'Конфиденциальность' },
  { id: 'data', label: 'Мои данные' },
]

function formatPhone(phone) {
  if (!phone) return null
  const d = phone.replace(/\D/g, '')
  if (d.length === 11) return `+${d[0]} ${d.slice(1, 4)} ${d.slice(4, 7)}-${d.slice(7, 9)}-${d.slice(9)}`
  return phone
}

function formatDate(iso) {
  if (!iso) return null
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })
}

// ---- Tab: Profile ----------------------------------------------------------

function ProfileTab({ profile, memories, onRemoveMemory, onUpdateName }) {
  const [editing, setEditing] = useState(false)
  const [nameInput, setNameInput] = useState(profile?.display_name || profile?.fio || '')

  const handleSaveName = () => {
    if (nameInput.trim()) {
      onUpdateName(nameInput.trim())
    }
    setEditing(false)
  }

  const name = profile?.display_name || profile?.fio
  const completeness = Math.round((profile?.completeness || 0) * 100)
  const portalRoleLabel = { 3: 'Родитель', 4: 'Ученик', 5: 'Гость' }[profile?.portal_role] || null

  return (
    <div className="flex flex-col gap-4">
      {/* Avatar + Name */}
      <div className="flex items-center gap-3">
        {profile?.avatar ? (
          <img src={profile.avatar} alt="" className="w-14 h-14 rounded-full object-cover shrink-0" />
        ) : (
          <div className="w-14 h-14 rounded-full bg-brand/15 flex items-center justify-center text-[22px] font-semibold text-brand shrink-0">
            {name ? name[0].toUpperCase() : '?'}
          </div>
        )}
        <div className="flex-1 min-w-0">
          {editing ? (
            <div className="flex gap-2">
              <input
                className="flex-1 px-3 py-1.5 rounded-lg text-[15px] bg-[var(--bg-secondary)] border border-[var(--border-subtle)] text-[var(--text-primary)] outline-none focus:border-[var(--color-brand)]"
                value={nameInput}
                onChange={e => setNameInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSaveName()}
                autoFocus
              />
              <button onClick={handleSaveName} className="px-3 py-1.5 rounded-lg bg-brand text-white text-[13px] font-medium">OK</button>
              <button onClick={() => setEditing(false)} className="px-2 py-1.5 text-[13px] text-[var(--text-secondary)]">Отмена</button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-[18px] font-semibold text-[var(--text-primary)] truncate">{name || 'Не указано'}</span>
              <button onClick={() => { setNameInput(name || ''); setEditing(true) }} className="text-[12px] text-brand hover:underline shrink-0">Изменить</button>
            </div>
          )}
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            {profile?.phone && (
              <span className="text-[13px] text-[var(--text-secondary)]">
                {formatPhone(profile.phone)}
                {profile.dms_verified && <span className="ml-1.5 text-brand">Подтверждён</span>}
              </span>
            )}
            {portalRoleLabel && (
              <span className="text-[11px] px-1.5 py-0.5 rounded-md bg-brand/10 text-brand">{portalRoleLabel}</span>
            )}
            {profile?.is_minor === true && (
              <span className="text-[11px] px-1.5 py-0.5 rounded-md bg-amber-100 text-amber-700">Несовершеннолетний</span>
            )}
          </div>
        </div>
      </div>

      {/* Completeness */}
      <div className="px-1">
        <div className="flex justify-between text-[12px] text-[var(--text-tertiary)] mb-1">
          <span>Профиль заполнен</span>
          <span>{completeness}%</span>
        </div>
        <div className="h-1.5 rounded-full bg-[var(--bg-secondary)] overflow-hidden">
          <div className="h-full rounded-full bg-brand transition-all duration-500" style={{ width: `${completeness}%` }} />
        </div>
      </div>

      {/* Children */}
      {profile?.children?.length > 0 && (
        <div className="rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] p-3">
          <div className="text-[12px] font-medium text-[var(--text-secondary)] mb-2 uppercase tracking-wide">Дети</div>
          {profile.children.map((child, i) => (
            <div key={i} className="flex items-center gap-2 py-1.5 border-t border-[var(--border-subtle)] first:border-t-0">
              <span className="text-[14px] text-[var(--text-primary)]">{child.fio || 'Без имени'}</span>
              {child.grade && <span className="text-[12px] text-[var(--text-secondary)]">{child.grade} класс</span>}
              {child.product_name && <span className="text-[11px] px-1.5 py-0.5 rounded-md bg-brand/10 text-brand">{child.product_name}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Stats */}
      <div className="flex gap-3">
        <div className="flex-1 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] p-3 text-center">
          <div className="text-[20px] font-bold text-[var(--text-primary)]">{profile?.stats?.conversation_count || 0}</div>
          <div className="text-[11px] text-[var(--text-tertiary)]">Разговоров</div>
        </div>
        <div className="flex-1 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] p-3 text-center">
          <div className="text-[20px] font-bold text-[var(--text-primary)]">{profile?.stats?.memory_count || 0}</div>
          <div className="text-[11px] text-[var(--text-tertiary)]">Фактов</div>
        </div>
      </div>

      {/* Memory items */}
      {memories.length > 0 && (
        <div className="rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] p-3">
          <div className="text-[12px] font-medium text-[var(--text-secondary)] mb-2 uppercase tracking-wide">Что Эврика знает</div>
          {memories.map(m => (
            <div key={m.id} className="flex items-center justify-between py-1.5 border-t border-[var(--border-subtle)] first:border-t-0 group">
              <span className="text-[13px] text-[var(--text-primary)] flex-1 min-w-0 truncate">{m.text}</span>
              <button
                onClick={() => onRemoveMemory(m.id)}
                className="ml-2 text-[12px] text-[var(--text-tertiary)] hover:text-[var(--error-color)] opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
              >
                Удалить
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---- Tab: Privacy ----------------------------------------------------------

function PrivacyTab({ consents, onToggleConsent, memories, onClearMemories }) {
  const [confirmClear, setConfirmClear] = useState(false)

  return (
    <div className="flex flex-col gap-4">
      {/* Consents */}
      <div className="rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] p-3">
        <div className="text-[12px] font-medium text-[var(--text-secondary)] mb-2 uppercase tracking-wide">Согласия</div>
        {consents.map(c => (
          <div key={c.purpose_id} className="flex items-start justify-between py-2.5 border-t border-[var(--border-subtle)] first:border-t-0">
            <div className="flex-1 min-w-0 pr-3">
              <div className="text-[14px] text-[var(--text-primary)] font-medium">{c.title_ru}</div>
              <div className="text-[12px] text-[var(--text-secondary)] mt-0.5">{c.description}</div>
              {c.granted && c.granted_at && (
                <div className="text-[11px] text-[var(--text-tertiary)] mt-0.5">Принято: {formatDate(c.granted_at)}</div>
              )}
              {c.required && <div className="text-[11px] text-brand mt-0.5">Обязательное</div>}
            </div>
            <label className="relative inline-flex items-center cursor-pointer shrink-0 mt-1">
              <input
                type="checkbox"
                checked={c.granted}
                onChange={e => onToggleConsent(c.purpose_id, e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-[var(--bg-secondary)] peer-focus:ring-2 peer-focus:ring-brand/30 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-[var(--border-subtle)] after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-brand" />
            </label>
          </div>
        ))}
      </div>

      {/* Memory control */}
      {memories.length > 0 && (
        <div className="rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] p-3">
          <div className="text-[12px] font-medium text-[var(--text-secondary)] mb-2 uppercase tracking-wide">Память</div>
          <div className="text-[13px] text-[var(--text-primary)] mb-3">
            Эврика запомнила {memories.length} факт(ов) из ваших разговоров.
          </div>
          {!confirmClear ? (
            <button
              onClick={() => setConfirmClear(true)}
              className="text-[13px] text-[var(--error-color)] hover:underline"
            >
              Очистить всю память
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-[13px] text-[var(--text-secondary)]">Точно удалить?</span>
              <button
                onClick={() => { onClearMemories(); setConfirmClear(false) }}
                className="px-3 py-1 rounded-lg bg-[var(--error-color)] text-white text-[12px] font-medium"
              >
                Да, удалить всё
              </button>
              <button onClick={() => setConfirmClear(false)} className="text-[12px] text-[var(--text-secondary)]">Отмена</button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---- Tab: Data -------------------------------------------------------------

function DataTab({ onExport, deletion, onRequestDeletion, onCancelDeletion }) {
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleteReason, setDeleteReason] = useState('')

  return (
    <div className="flex flex-col gap-4">
      {/* Export */}
      <div className="rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] p-3">
        <div className="text-[12px] font-medium text-[var(--text-secondary)] mb-2 uppercase tracking-wide">Экспорт данных</div>
        <div className="text-[13px] text-[var(--text-primary)] mb-3">
          Скачайте все ваши данные: профиль, разговоры, память, согласия.
        </div>
        <button
          onClick={onExport}
          className="px-4 py-2 rounded-lg bg-brand text-white text-[13px] font-medium hover:bg-[var(--color-brand-hover)] transition-colors"
        >
          Скачать данные (JSON)
        </button>
      </div>

      {/* Deletion */}
      <div className="rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] p-3">
        <div className="text-[12px] font-medium text-[var(--text-secondary)] mb-2 uppercase tracking-wide">Удаление аккаунта</div>

        {deletion ? (
          <div>
            <div className="text-[13px] text-[var(--error-color)] mb-2">
              Запрос на удаление отправлен. Данные будут удалены {formatDate(deletion.execute_after)}.
            </div>
            <div className="text-[12px] text-[var(--text-secondary)] mb-3">
              В течение этого времени вы можете отменить запрос.
            </div>
            <button
              onClick={onCancelDeletion}
              className="px-4 py-2 rounded-lg border border-[var(--border-default)] text-[var(--text-primary)] text-[13px] font-medium hover:bg-[var(--bg-secondary)] transition-colors"
            >
              Отменить удаление
            </button>
          </div>
        ) : !showDeleteConfirm ? (
          <div>
            <div className="text-[13px] text-[var(--text-primary)] mb-3">
              Это удалит все ваши данные: профиль, разговоры, память, данные в CRM. Период восстановления — 30 дней.
            </div>
            <button
              onClick={() => setShowDeleteConfirm(true)}
              className="px-4 py-2 rounded-lg border border-[var(--error-color)] text-[var(--error-color)] text-[13px] font-medium hover:bg-[var(--error-bg)] transition-colors"
            >
              Удалить все мои данные
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <div className="text-[13px] text-[var(--error-color)] font-medium">Вы уверены?</div>
            <input
              className="px-3 py-1.5 rounded-lg text-[13px] bg-[var(--bg-secondary)] border border-[var(--border-subtle)] text-[var(--text-primary)] outline-none"
              placeholder="Причина (необязательно)"
              value={deleteReason}
              onChange={e => setDeleteReason(e.target.value)}
            />
            <div className="flex gap-2">
              <button
                onClick={() => { onRequestDeletion(deleteReason || null); setShowDeleteConfirm(false) }}
                className="px-4 py-2 rounded-lg bg-[var(--error-color)] text-white text-[13px] font-medium"
              >
                Подтвердить удаление
              </button>
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="px-3 py-2 text-[13px] text-[var(--text-secondary)]"
              >
                Отмена
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---- Main Page -------------------------------------------------------------

export function ProfilePage() {
  const auth = useMemo(() => buildAuthPayload(), [])
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('profile')

  const {
    profile, memories, consents, deletion,
    loading, error,
    updateName, removeMemory, clearAllMemories,
    toggleConsent,
    doExport, doRequestDeletion, doCancelDeletion,
  } = useProfile(auth)

  const handleBack = useCallback(() => {
    navigate('/')
  }, [navigate])

  if (loading) {
    return (
      <div className="w-full h-dvh flex items-center justify-center bg-[var(--bg-primary)]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-brand border-t-transparent rounded-full animate-spin" />
          <span className="text-[13px] text-[var(--text-secondary)]">Загрузка профиля...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="w-full h-dvh flex flex-col bg-[var(--bg-primary)]">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-3 bg-[var(--bg-elevated)] border-b border-[var(--border-subtle)] shrink-0">
        <button onClick={handleBack} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M12.5 15L7.5 10L12.5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </button>
        <h1 className="text-[16px] font-semibold text-[var(--text-primary)]">Профиль</h1>
      </header>

      {/* Tab bar */}
      <div className="flex px-4 pt-3 pb-1 gap-1 shrink-0">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 py-2 text-[13px] font-medium rounded-lg transition-colors ${
              activeTab === tab.id
                ? 'bg-brand text-white'
                : 'bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Error banner */}
      {error && (
        <div className="mx-4 mt-2 px-3 py-2 rounded-lg bg-[var(--error-bg)] border border-[var(--error-border)] text-[13px] text-[var(--error-color)]">
          {error}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {activeTab === 'profile' && (
          <ProfileTab
            profile={profile}
            memories={memories}
            onRemoveMemory={removeMemory}
            onUpdateName={updateName}
          />
        )}
        {activeTab === 'privacy' && (
          <PrivacyTab
            consents={consents}
            onToggleConsent={toggleConsent}
            memories={memories}
            onClearMemories={clearAllMemories}
          />
        )}
        {activeTab === 'data' && (
          <DataTab
            onExport={doExport}
            deletion={deletion}
            onRequestDeletion={doRequestDeletion}
            onCancelDeletion={doCancelDeletion}
          />
        )}
      </div>
    </div>
  )
}
