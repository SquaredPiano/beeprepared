"use client";

/**
 * Session token for backend calls.
 *
 * The backend signs its own tokens and serves a single local workspace, so
 * there is no identity provider to talk to.
 */

const STORAGE_KEY = "beeprepared.token";
const LOCAL_USER = "local-user";

export async function getAccessToken(): Promise<string> {
  if (typeof window === "undefined") return LOCAL_USER;

  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored) return stored;

  window.localStorage.setItem(STORAGE_KEY, LOCAL_USER);
  return LOCAL_USER;
}

export async function getUserId(): Promise<string> {
  return LOCAL_USER;
}

export async function isAuthenticated(): Promise<boolean> {
  return true;
}
