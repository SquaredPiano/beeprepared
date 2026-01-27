import { useMascotStore } from '@/store/useMascotStore';

type InteractionContext = {
  event: 'upload_complete' | 'quiz_result' | 'exam_start' | 'idle';
  data?: any;
};

export const useMascotAI = () => {
  const store = useMascotStore();

  const triggerReaction = async (context: InteractionContext) => {
    store.setMood('thinking');
    
    try {
      const response = await fetch('/api/mascot/react', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          context,
          userStats: { honeyPoints: 120 }
        }),
      });

      const { object } = await response.json();

      if (object.position) store.flyTo(object.position);
      
      if (object.mood === 'celebrating') {
        store.celebrate(object.message);
      } else {
        store.setMood(object.mood);
        store.say(object.message, object.duration);
      }

    } catch (error) {
      console.error("Mascot brain freeze:", error);
      store.setMood('idle');
    }
  };

  return { triggerReaction };
};
