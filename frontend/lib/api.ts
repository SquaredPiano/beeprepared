import { supabase } from "./supabase";

export interface Project {
  id: string;
  name: string;
  description?: string;
  nodes: any[];
  edges: any[];
  user_id: string;
  created_at: string;
  updated_at: string;
}

export interface Asset {
  id: string;
  filename: string;
  file_type: string;
  file_size: number;
  storage_url?: string;
  status: 'staged' | 'processing' | 'ready' | 'error';
  project_id?: string;
  created_at: string;
}

export interface Artifact {
  id: string;
  type: 'flashcard' | 'quiz' | 'exam' | 'pptx';
  content: any;
  metadata?: any;
  asset_id: string;
  created_at: string;
}

export const api = {
  projects: {
    async list() {
      const { data, error } = await supabase
        .from('projects')
        .select('*')
        .order('updated_at', { ascending: false });
      if (error) throw error;
      return data as Project[];
    },
    async create(name: string, description?: string) {
      const { data: userData } = await supabase.auth.getUser();
      const { data, error } = await supabase
        .from('projects')
        .insert({
          name,
          description,
          user_id: userData.user?.id,
          nodes: [],
          edges: []
        })
        .select()
        .single();
      if (error) throw error;
      return data as Project;
    },
    async delete(id: string) {
      const { error } = await supabase
        .from('projects')
        .delete()
        .eq('id', id);
      if (error) throw error;
    }
  },
  assets: {
    async list(projectId?: string) {
      let query = supabase.from('assets').select('*');
      if (projectId) {
        query = query.eq('project_id', projectId);
      } else {
        query = query.is('project_id', null);
      }
      const { data, error } = await query.order('created_at', { ascending: false });
      if (error) throw error;
      return data as Asset[];
    },
    async delete(id: string) {
      const { error } = await supabase
        .from('assets')
        .delete()
        .eq('id', id);
      if (error) throw error;
    }
  },
  artifacts: {
    async list(type?: string) {
      let query = supabase.from('artifacts').select('*');
      if (type) {
        query = query.eq('type', type);
      }
      const { data, error } = await query.order('created_at', { ascending: false });
      if (error) throw error;
      return data as Artifact[];
    }
  },
  points: {
    async getBalance() {
      const { data: userData } = await supabase.auth.getUser();
      if (!userData.user) return 0;
      const { data, error } = await supabase
        .from('honey_points')
        .select('amount')
        .eq('user_id', userData.user.id);
      if (error) throw error;
      return data.reduce((sum, entry) => sum + entry.amount, 0);
    }
  }
};
