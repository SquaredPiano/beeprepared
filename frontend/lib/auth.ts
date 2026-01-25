"use client";

import { supabase } from "./supabase";

/**
 * AuthError represents authentication-related errors.
 * Components can catch this to handle session expiry gracefully.
 */
export class AuthError extends Error {
    constructor(message: string) {
        super(message);
        this.name = "AuthError";
    }
}

/**
 * Get the current access token, refreshing if necessary.
 * 
 * This function:
 * 1. Retrieves the current session
 * 2. Checks if the token is about to expire (30s buffer)
 * 3. Refreshes the token if needed
 * 4. Returns a valid access token or throws AuthError
 * 
 * @throws AuthError if no valid session exists or refresh fails
 */
export async function getAccessToken(): Promise<string> {
    const { data: { session }, error } = await supabase.auth.getSession();

    if (error) {
        console.error("[Auth] Session error:", error.message);
        throw new AuthError("Session error: " + error.message);
    }

    if (!session) {
        throw new AuthError("Not authenticated");
    }

    // Check if token is expiring soon (within 30 seconds)
    const expiresAt = session.expires_at;
    const expiresIn = expiresAt ? (expiresAt * 1000) - Date.now() : Infinity;

    if (expiresIn < 30000) {
        console.log("[Auth] Token expiring soon, refreshing...");
        const { data: refreshed, error: refreshError } = await supabase.auth.refreshSession();

        if (refreshError) {
            console.error("[Auth] Refresh failed:", refreshError.message);
            throw new AuthError("Session expired, please log in again");
        }

        if (!refreshed.session) {
            throw new AuthError("Session expired");
        }

        console.log("[Auth] Token refreshed successfully");
        return refreshed.session.access_token;
    }

    return session.access_token;
}

/**
 * Check if user is currently authenticated.
 * Non-throwing version of getAccessToken for conditional checks.
 */
export async function isAuthenticated(): Promise<boolean> {
    try {
        await getAccessToken();
        return true;
    } catch {
        return false;
    }
}

/**
 * Get user ID from current session.
 * @throws AuthError if not authenticated
 */
export async function getUserId(): Promise<string> {
    const { data: { session } } = await supabase.auth.getSession();

    if (!session?.user?.id) {
        throw new AuthError("Not authenticated");
    }

    return session.user.id;
}
