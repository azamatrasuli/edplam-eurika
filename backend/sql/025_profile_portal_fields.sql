-- 025: Добавить поля из портала в agent_user_profiles (avatar, portal_role, is_minor)
-- Нужно для синхронизации данных из JWT портала в профиль Эврики.

ALTER TABLE agent_user_profiles ADD COLUMN IF NOT EXISTS avatar TEXT;
ALTER TABLE agent_user_profiles ADD COLUMN IF NOT EXISTS portal_role INT;       -- 3=parent, 4=student, 5=guest
ALTER TABLE agent_user_profiles ADD COLUMN IF NOT EXISTS is_minor BOOLEAN;
