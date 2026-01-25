import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { Hexagon } from 'lucide-react';

export const KnowledgeCoreNode = memo(() => {
    return (
        <div className="px-4 py-4 shadow-xl rounded-full bg-honey border-2 border-bee-black w-[160px] h-[160px] flex flex-col items-center justify-center animate-pulse-slow">
            <Hexagon size={48} className="text-bee-black mb-2" />
            <div className="text-base font-black uppercase tracking-tight text-center leading-none">Knowledge<br />Core</div>

            <Handle type="target" position={Position.Top} className="w-3 h-3 bg-bee-black" />
            <Handle type="source" position={Position.Bottom} className="w-3 h-3 bg-bee-black" />
        </div>
    );
});
