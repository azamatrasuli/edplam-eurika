import { useEffect, useMemo, useRef, useState } from 'react'
import { checkProfile, verifyOnboarding } from '../api/client'

const STEPS = {
  CHECKING: 'checking',
  COMPLETE: 'complete',
}

function profileStorageKey(actorId) {
  return `eurika_profile_${actorId}`
}

/**
 * Invisible onboarding hook.
 *
 * - Portal (has phone from JWT): silent auto-verify in DMS → straight to chat.
 * - Telegram / External (no phone): skip to chat immediately, LLM qualifies.
 * - Returning users: profile restored from backend.
 */
export function useOnboarding(auth, actorId, actorPhone) {
  const [step, setStep] = useState(STEPS.CHECKING)
  const [profileData, setProfileData] = useState(null)
  const [error, setError] = useState('')
  const initDone = useRef(false)

  useEffect(() => {
    if (!auth || initDone.current) return
    initDone.current = true

    ;(async () => {
      try {
        // 1. Quick localStorage check for returning users
        if (actorId) {
          const cached = localStorage.getItem(profileStorageKey(actorId))
          if (cached) {
            try {
              const parsed = JSON.parse(cached)
              if (parsed && parsed.profile_id) {
                const res = await checkProfile(auth)
                if (res.has_profile) {
                  setProfileData(res.profile)
                  setStep(STEPS.COMPLETE)
                  return
                }
                try { localStorage.removeItem(profileStorageKey(actorId)) } catch { /* */ }
              }
            } catch {
              localStorage.removeItem(profileStorageKey(actorId))
            }
          }
        }

        // 2. Check backend for existing profile
        const res = await checkProfile(auth)
        if (res.has_profile) {
          setProfileData(res.profile)
          if (actorId) {
            try { localStorage.setItem(profileStorageKey(actorId), JSON.stringify({ profile_id: res.profile.id })) } catch { /* quota */ }
          }
          setStep(STEPS.COMPLETE)
          return
        }

        // 3. Portal with phone → silent auto-verify (no UI)
        if (actorPhone) {
          try {
            const verifyRes = await verifyOnboarding(auth, {
              client_type: 'existing',
              user_role: 'parent',
              phone: actorPhone,
              students: [],
            })
            setProfileData(verifyRes)
            if (actorId && verifyRes) {
              try { localStorage.setItem(profileStorageKey(actorId), JSON.stringify({ profile_id: verifyRes.profile_id || '' })) } catch { /* quota */ }
            }
          } catch {
            // Auto-verify failed — continue without profile, LLM will handle
          }
          setStep(STEPS.COMPLETE)
          return
        }

        // 4. Telegram / External without phone → skip to chat
        //    LLM handles qualification through conversation
        setStep(STEPS.COMPLETE)
      } catch (e) {
        setError(e.message)
        // On any error — skip to chat, don't block the user
        setStep(STEPS.COMPLETE)
      }
    })()
  }, [auth, actorId, actorPhone])

  const isComplete = step === STEPS.COMPLETE
  const isChecking = step === STEPS.CHECKING

  return useMemo(
    () => ({
      step,
      messages: [], // No onboarding messages — everything in chat now
      isComplete,
      isChecking,
      profileData,
      error,
      handleButtonClick: () => {},
      handleFormSubmit: () => {},
    }),
    [step, isComplete, isChecking, profileData, error],
  )
}
