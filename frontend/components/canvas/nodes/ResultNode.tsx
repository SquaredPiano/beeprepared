import { Handle, Position, type NodeProps, useReactFlow } from '@xyflow/react'
import { BookOpen, Trophy, GraduationCap, Eye } from 'lucide-react'
import { motion } from 'framer-motion'
import Link from 'next/link'
import { NodeContextMenu } from '../NodeContextMenu'
import { useCanvasStore } from '@/store/useCanvasStore'

export function ResultNode({ id, data }: NodeProps & { id: string }) {
  const Icon = data.type === 'flashcards' ? BookOpen : data.type === 'quiz' ? Trophy : GraduationCap
  const { setNodes, getNodes } = useReactFlow()
  const { takeSnapshot } = useCanvasStore()

  const handleDelete = () => {
    setNodes(getNodes().filter(node => node.id !== id))
    takeSnapshot()
  }

  return (
    <NodeContextMenu
      nodeType="result"
      onDelete={handleDelete}
      onPractice={() => {
        // Practice logic
      }}
    >
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="px-4 py-3 shadow-2xl rounded-2xl bg-white border-2 border-honey min-w-[200px] group relative"
      >
        <div className="flex items-center gap-3">
          <div className="p-2 bg-honey text-white rounded-xl shadow-lg shadow-honey/20">
            <Icon className="w-5 h-5" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[10px] font-bold text-honey uppercase tracking-[0.2em]">Result</p>
            <p className="text-sm font-bold text-bee-black truncate">{String(data.label || 'Artifact')}</p>
          </div>
        </div>

        <div className="mt-3 pt-3 border-t border-wax flex justify-between items-center">
          <span className="text-[10px] font-medium text-bee-black/40 italic">Ready for review</span>
          <Link
            href={data.href || `/artifacts/${id}`}
            className="flex items-center gap-1.5 text-[10px] font-bold text-honey hover:text-bee-black transition-colors"
          >
            VIEW <Eye className="w-3 h-3" />
          </Link>
        </div>

        <Handle
          type="target"
          position={Position.Left}
          className="w-3 h-3 bg-honey border-2 border-white !-left-1.5"
        />
      </motion.div>
    </NodeContextMenu>
  )
}
