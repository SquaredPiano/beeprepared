// Mock Project - bypasses backend project API for demo/dev purposes

export interface MockProject {
    id: string;
    name: string;
    description?: string;
    user_id: string;
    created_at: string;
    updated_at: string;
    canvas_state?: {
        viewport: { x: number; y: number; zoom: number };
        nodes: any[];
        edges: any[];
    };
}

export const mockProjects: MockProject[] = [
    {
        id: "proj-demo-1",
        name: "Demo Project",
        description: "A demo project for testing",
        user_id: "mock-user-id",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        canvas_state: {
            viewport: { x: 0, y: 0, zoom: 1 },
            nodes: [],
            edges: [],
        },
    },
];

export async function getMockProjects(): Promise<MockProject[]> {
    return mockProjects;
}

export async function getMockProjectById(id: string): Promise<MockProject | null> {
    return mockProjects.find((p) => p.id === id) || null;
}

export async function createMockProject(name: string, description?: string): Promise<MockProject> {
    const newProj: MockProject = {
        id: `proj-${Date.now()}`,
        name,
        description,
        user_id: "mock-user-id",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        canvas_state: {
            viewport: { x: 0, y: 0, zoom: 1 },
            nodes: [],
            edges: [],
        },
    };
    mockProjects.push(newProj);
    return newProj;
}

export async function updateMockProject(
    id: string,
    updates: Partial<Pick<MockProject, "name" | "description" | "canvas_state">>
): Promise<MockProject | null> {
    const idx = mockProjects.findIndex((p) => p.id === id);
    if (idx === -1) return null;

    mockProjects[idx] = {
        ...mockProjects[idx],
        ...updates,
        updated_at: new Date().toISOString(),
    };
    return mockProjects[idx];
}
