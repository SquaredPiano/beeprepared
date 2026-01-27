import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

export interface TaskStatus {
  task_id: string;
  status: 'pending' | 'processing' | 'complete' | 'failed';
  progress: number;
  stage: string;
  eta_seconds?: number;
  artifact_id?: string;
  error?: string;
}

export function useTaskPolling(taskId: string | null) {
  return useQuery({
    queryKey: ['task', taskId],
    queryFn: async () => {
      const { data } = await axios.get<TaskStatus>(`/api/tasks/${taskId}/status`);
      return data;
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      // Stop polling if complete or failed
      if (status === 'complete' || status === 'failed') {
        return false;
      }
      return 2000; // Poll every 2 seconds
    },
    enabled: !!taskId,
  });
}
