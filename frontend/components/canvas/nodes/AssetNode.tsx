import { Handle, Position, type NodeProps } from '@xyflow/react'
import { FileText, Video, Presentation, MoreVertical } from 'lucide-react'
import { motion } from 'framer-motion'

export function AssetNode({ data }: NodeProps) {
  const Icon = data.type === 'video' ? Video : data.type === 'pptx' ? Presentation : FileText

  return (
    <motion.div 
      initial={{ scale: 0.9, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      className="px-4 py-3 shadow-xl rounded-2xl bg-white border border-wax min-w-[180px] group relative"
    >
      <div className="flex items-center gap-3">
        <div className="p-2 bg-honey/10 rounded-xl text-honey group-hover:bg-honey group-hover:text-white transition-all duration-300">
          <Icon className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-bee-black/40 uppercase tracking-wider">Asset</p>
          <p className="text-sm font-bold text-bee-black truncate">{data.label || 'Untitled'}</p>
        </div>
        <button className="text-bee-black/20 hover:text-bee-black transition-colors">
          <MoreVertical className="w-4 h-4" />
        </button>
      </div>
      
      {/* Handles */}
      <Handle 
        type="source" 
        position={Position.Right} 
        className="w-3 h-3 bg-honey border-2 border-white !-right-1.5"
      />
    </motion.div>
  )
}
