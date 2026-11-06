/** An admin sees (and the server allows) administrator functions only while their session is in admin view. */
export const inAdminView = (u: { is_admin: boolean; acting_as_user?: boolean }) => u.is_admin && !u.acting_as_user;
