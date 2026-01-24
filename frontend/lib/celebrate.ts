import confetti from 'canvas-confetti';
import { toast } from 'sonner';

export function celebrateLevelUp() {
  confetti({
    particleCount: 150,
    spread: 80,
    origin: { y: 0.6 },
    colors: ['#FBBF24', '#F59E0B', '#D97706'],
    ticks: 200,
    gravity: 1.2,
    scalar: 1.2,
    shapes: ['circle', 'square'],
  });
  
  toast.success("Level Up! You're now a Worker Bee!", {
    description: "You've earned more honey drops for your hive.",
    icon: '🐝',
    duration: 5000,
  });
}
