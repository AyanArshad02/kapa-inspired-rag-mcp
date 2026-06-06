-- Add is_admin flag for RBAC. Existing users default to false.
-- To grant admin: UPDATE users SET is_admin = TRUE WHERE email = 'your@email.com';
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;
