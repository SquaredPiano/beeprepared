import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { FileText, Video, Mic, FileQuestion, File } from 'lucide-react';

const icons = {
    pdf: FileText,
    video: Video,
    audio: Mic,
    youtube: Video,
    md: File,
    pptx: FileQuestion
};

export const SourceNode = memo(({ data }: { data: { type: string; label: string } }) => {
    const Icon = icons[data.type as keyof typeof icons] || File;

    return (
        <div className="px-4 py-2 shadow-md rounded-md bg-white border-2 border-bee-black min-w-[150px]">
            <div className="flex items-center">
                <div className="rounded-full w-8 h-8 flex justify-center items-center bg-gray-100 mr-2">
                    <Icon size={16} />
                </div>
                <div className="text-sm font-bold truncate max-w-[120px]">{data.label}</div>
            </div>
            <Handle type="source" position={Position.Bottom} className="w-3 h-3 bg-bee-black" />
        </div>
    );
});
