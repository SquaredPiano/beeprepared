import { Handle, Position, type NodeProps, useReactFlow } from '@xyflow/react'
import { Sparkles, Loader2, CheckCircle2 } from 'lucide-react'
import { motion } from 'framer-motion'
import { NodeContextMenu } from '../NodeContextMenu'
import { useCanvasStore } from '@/store/useCanvasStore'

export function ProcessNode({ id, data }: NodeProps & { id: string }) {
  const status = data.status || 'pending'
  const { deleteNodes } = useReactFlow()
  const { takeSnapshot } = useCanvasStore()

  return (
    <NodeContextMenu 
      nodeType="process"
      onDelete={() => {
        deleteNodes([{ id }])
        takeSnapshot()
      }}
      onRerun={() => {
        // Logic for re-running synthesis
      }}
    >
      <motion.div 
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="px-4 py-3 shadow-xl rounded-2xl bg-bee-black border border-bee-black/20 min-w-[160px] group relative"
      >
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-xl transition-all duration-300 ${
            status === 'completed' ? 'bg-green-500/20 text-green-500' : 
            status === 'processing' ? 'bg-honey/20 text-honey' : 'bg-white/10 text-white/40'
          }`}>
            {status === 'processing' ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : status === 'completed' ? (
              <CheckCircle2 className="w-5 h-5" />
            ) : (
              <Sparkles className="w-5 h-5" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[10px] font-bold text-white/40 uppercase tracking-[0.2em]">Process</p>
            <p className="text-sm font-bold text-white truncate">{data.label || 'Task'}</p>
          </div>
        </div>
  
        <Handle 
          type="target" 
          position={Position.Left} 
          className="w-3 h-3 bg-honey border-2 border-bee-black !-left-1.5"
        />
        <Handle 
          type="source" 
          position={Position.Right} 
          className="w-3 h-3 bg-honey border-2 border-bee-black !-right-1.5"
        />
      </motion.div>
    </NodeContextMenu>
  )
}
