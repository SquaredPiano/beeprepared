import { memo, useCallback } from 'react';
import { Handle, Position } from '@xyflow/react';
import { Play, Eye, Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import { useArtifactGenerator, TargetType, JobStatus } from '@/hooks/useArtifactGenerator';
import { cn } from '@/lib/utils'; // Assuming cn exists, else standard string concat

interface GeneratorNodeProps {
    data: {
        projectId: string;
        knowledgeCoreId: string | null;
        targetType: TargetType;
        label: string;
        onViewResult: (artifact: any, type: TargetType) => void;
    }
}

export const GeneratorNode = memo(({ data }: GeneratorNodeProps) => {
    const { states, generate, isGenerating } = useArtifactGenerator();
    const state = states[data.targetType];

    const isDisabled = !data.knowledgeCoreId || (isGenerating && state.status !== 'running');
    const isRunning = state.status === 'running' || state.status === 'pending';
    const isCompleted = state.status === 'completed';

    const handleGenerate = useCallback(async () => {
        if (!data.knowledgeCoreId || !data.projectId) return;
        await generate(data.projectId, data.knowledgeCoreId, data.targetType);
    }, [generate, data.projectId, data.knowledgeCoreId, data.targetType]);

    const handleView = useCallback(() => {
        if (state.artifact) {
            data.onViewResult(state.artifact, data.targetType);
        }
    }, [state.artifact, data.targetType, data.onViewResult]);

    return (
        <div className={cn(
            "px-4 py-3 shadow-lg rounded-xl bg-white border-2 border-wax w-[220px] transition-all",
            isDisabled && "opacity-50 grayscale",
            isCompleted && "border-green-500 bg-green-50",
            state.status === 'failed' && "border-red-500 bg-red-50"
        )}>
            <Handle type="target" position={Position.Top} className="w-3 h-3 bg-bee-black" />

            <div className="flex flex-col gap-3">
                <div className="flex justify-between items-center">
                    <span className="font-bold uppercase tracking-tight text-sm">{data.label}</span>
                    {isRunning && <Loader2 size={14} className="animate-spin text-honey" />}
                    {isCompleted && <CheckCircle2 size={14} className="text-green-600" />}
                    {state.status === 'failed' && <AlertCircle size={14} className="text-red-500" />}
                </div>

                {state.progress > 0 && state.progress < 100 && (
                    <div className="h-1 w-full bg-gray-100 rounded-full overflow-hidden">
                        <div className="h-full bg-honey transition-all duration-500" style={{ width: `${state.progress}%` }} />
                    </div>
                )}

                <div className="flex gap-2">
                    {!isCompleted ? (
                        <button
                            onClick={handleGenerate}
                            disabled={isDisabled || isRunning}
                            className="flex-1 flex items-center justify-center gap-2 bg-bee-black text-white py-1.5 rounded-lg text-xs font-bold uppercase tracking-wide hover:bg-honey hover:text-bee-black disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
                        >
                            {isRunning ? 'Building...' : <><Play size={10} /> Generate</>}
                        </button>
                    ) : (
                        <button
                            onClick={handleView}
                            className="flex-1 flex items-center justify-center gap-2 bg-green-600 text-white py-1.5 rounded-lg text-xs font-bold uppercase tracking-wide hover:bg-green-700 transition-colors"
                        >
                            <Eye size={10} /> Result
                        </button>
                    )}
                </div>

                {state.error && (
                    <p className="text-[10px] text-red-500 leading-tight">{state.error}</p>
                )}
            </div>
        </div>
    );
});
