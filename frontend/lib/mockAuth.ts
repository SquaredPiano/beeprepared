// Mock Auth - bypasses Supabase completely for demo/dev purposes

export const mockUser = {
    id: "mock-user-id",
    email: "test@example.com",
    name: "Test User",
};

export async function getMockSession() {
    return {
        user: mockUser,
        accessToken: "mock-token",
        expires_at: Date.now() / 1000 + 3600, // 1 hour from now
    };
}

export async function getMockAccessToken(): Promise<string> {
    return "mock-token";
}

export function isMockAuth(): boolean {
    return true;
}
