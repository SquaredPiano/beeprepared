import { google } from '@ai-sdk/google';
import { generateObject } from 'ai';
import { z } from 'zod';

const mascotSchema = z.object({
  message: z.string().describe("The text to display in the speech bubble. Max 15 words. Witty, studious, bee-themed."),
  mood: z.enum(['idle', 'happy', 'thinking', 'celebrating', 'hidden']),
  position: z.enum(['bottom-right', 'center', 'top-right']),
  duration: z.number().default(4000).describe("How long to show the message in ms"),
});

export async function POST(req: Request) {
  try {
    const { context, userStats } = await req.json();

    const result = await generateObject({
      model: google('gemini-2.0-flash-001'),
      schema: mascotSchema,
      system: `
        You are the mascot for BeePrepared, an intentional knowledge architecture platform.
        You are a studious, friendly bee wearing a graduation cap.
        
        Your goal is to encourage students as they process complex PDFs and take exams.
        
        Guidelines:
        1. Be concise. Speech bubbles have limited space (Max 15 words).
        2. Use the "Hive" metaphor subtly (pollinating knowledge, building cells, refining honey).
        3. If the user fails a quiz, be empathetic but constructive.
        4. If the user ingests a large file, be impressed by the workload.
        5. NEVER use emojis. Use words to convey emotion.
      `,
      prompt: `
        User Context: ${JSON.stringify(context)}
        User Stats: ${JSON.stringify(userStats)}
        
        React to this situation.
      `,
    });

    return Response.json(result);
  } catch (error) {
    console.error("Mascot API error:", error);
    return Response.json({ error: "Failed to generate reaction" }, { status: 500 });
  }
}
