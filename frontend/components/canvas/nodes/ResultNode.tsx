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
        className="px-4 py-3 shadow-md rounded-xl bg-white border border-gray-100 min-w-[220px] group relative hover:shadow-lg transition-all"
      >
        <div className="flex items-center gap-3">
          <div className="p-2 bg-gray-50 text-gray-900 rounded-lg border border-gray-100">
            <Icon className="w-4 h-4" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest font-sans">Result</p>
            <p className="text-sm font-semibold text-gray-900 truncate font-sans">{String(data.label || 'Artifact')}</p>
          </div>
        </div>

        <div className="mt-3 pt-3 border-t border-gray-50 flex justify-between items-center">
          <span className="text-[10px] font-medium text-gray-400 font-sans">Ready</span>
          <Link
            href={data.href || `/artifacts/${id}`}
            className="flex items-center gap-1.5 text-[10px] font-bold text-gray-900 hover:text-blue-600 transition-colors bg-gray-50 px-2 py-1 rounded-full uppercase tracking-wider"
          >
            Open
          </Link>
        </div>

        <Handle
          type="target"
          position={Position.Left}
          className="w-2 h-2 bg-gray-300 border-2 border-white !-left-1"
        />
      </motion.div>
    </NodeContextMenu>
  )
}
