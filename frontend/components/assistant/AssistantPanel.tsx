"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Loader2, MessageCircle, Send, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { api, ChatMessage, GeneratedType } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The assistant panel.
 *
 * Generation used to be a slot machine: if the quiz came out too easy, the only
 * option was to click generate again and hope. This is the "say what you want"
 * path - the backend classifies each message as either a question to answer or
 * a change to make, and a change queues a refine job against whatever artifact
 * is currently open.
 *
 * The panel does not poll for the refine job. It is told when the job finishes
 * through the same WebSocket the canvas uses; `onJobQueued` hands the job id up
 * so the page can wire that in.
 */

interface AssistantPanelProps {
  projectId: string | null;
  /** The artifact currently in view. Refinement targets this. */
  artifactId?: string | null;
  artifactType?: string | null;
  /** Called when the assistant queues a refine job. */
  onJobQueued?: (jobId: string, targetType?: GeneratedType) => void;
}

interface Turn {
  id: string;
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
  action?: string;
}

// Shown when there is no history yet - concrete examples teach the interaction
// far better than a "How can I help?" placeholder.
const SUGGESTIONS = [
  "Make the questions harder",
  "Focus on the second half of the lecture",
  "Add a worked example to each section",
  "Explain why this answer is correct",
];

export function AssistantPanel({
  projectId,
  artifactId,
  artifactType,
  onJobQueued,
}: AssistantPanelProps) {
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Load history the first time the panel is opened, not on mount - most
  // sessions never open it, and this is a request per project.
  useEffect(() => {
    if (!open || !projectId || turns.length > 0) return;

    api.chat
      .history(projectId)
      .then((messages: ChatMessage[]) =>
        setTurns(
          messages.map((message) => ({
            id: message.id,
            role: message.role,
            content: message.content,
            action: message.metadata?.action,
          })),
        ),
      )
      .catch(() => undefined);
  }, [open, projectId, turns.length]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || !projectId || sending) return;

      const userTurn: Turn = { id: `u-${Date.now()}`, role: "user", content: message };
      const thinking: Turn = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content: "",
        pending: true,
      };

      setTurns((previous) => [...previous, userTurn, thinking]);
      setDraft("");
      setSending(true);

      try {
        const reply = await api.chat.send(projectId, message, artifactId ?? undefined);

        setTurns((previous) =>
          previous.map((turn) =>
            turn.id === thinking.id
              ? { ...turn, content: reply.reply, pending: false, action: reply.action }
              : turn,
          ),
        );

        if (reply.job_id) {
          onJobQueued?.(reply.job_id, reply.target_type);
          toast.loading(`Rebuilding your ${reply.target_type ?? "artifact"}…`, {
            id: reply.job_id,
          });
        }
      } catch (error: any) {
        setTurns((previous) =>
          previous.map((turn) =>
            turn.id === thinking.id
              ? { ...turn, content: `I could not do that: ${error.message}`, pending: false }
              : turn,
          ),
        );
      } finally {
        setSending(false);
      }
    },
    [projectId, artifactId, sending, onJobQueued],
  );

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends, Shift+Enter is a newline - the convention every chat UI uses.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send(draft);
    }
  };

  if (!projectId) return null;

  return (
    <>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 24, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.96 }}
            transition={{ type: "spring", stiffness: 320, damping: 28 }}
            className="fixed bottom-24 right-6 z-50 flex h-[32rem] w-[24rem] max-w-[calc(100vw-3rem)] flex-col overflow-hidden rounded-3xl border border-border/50 bg-background/95 shadow-2xl backdrop-blur-xl"
            role="dialog"
            aria-label="Study assistant"
          >
            <header className="flex items-center justify-between border-b border-border/40 px-5 py-4">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-honey-500" />
                <div>
                  <p className="text-sm font-semibold leading-none">Assistant</p>
                  <p className="mt-1 text-[11px] opacity-50">
                    {artifactType ? `Editing your ${artifactType}` : "Ask about your material"}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="rounded-lg p-1.5 opacity-50 transition hover:bg-muted hover:opacity-100"
                aria-label="Close assistant"
              >
                <X className="h-4 w-4" />
              </button>
            </header>

            <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
              {turns.length === 0 && (
                <div className="space-y-3 pt-6 text-center">
                  <p className="text-sm opacity-60">
                    Tell me what to change and I&apos;ll rebuild it.
                  </p>
                  <div className="flex flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map((suggestion) => (
                      <button
                        key={suggestion}
                        onClick={() => void send(suggestion)}
                        className="rounded-full border border-border/50 px-3 py-1.5 text-[11px] transition hover:border-honey-500/60 hover:bg-honey-500/10"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {turns.map((turn) => (
                <div
                  key={turn.id}
                  className={cn("flex", turn.role === "user" ? "justify-end" : "justify-start")}
                >
                  <div
                    className={cn(
                      "max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
                      turn.role === "user"
                        ? "bg-honey-500 text-bee-black"
                        : "border border-border/40 bg-muted/50",
                    )}
                  >
                    {turn.pending ? (
                      <span className="flex items-center gap-2 opacity-60">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Thinking…
                      </span>
                    ) : (
                      <>
                        {turn.content}
                        {turn.action === "refine" && (
                          <span className="mt-2 flex items-center gap-1.5 text-[11px] opacity-60">
                            <Sparkles className="h-3 w-3" />
                            Rebuilding now
                          </span>
                        )}
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="border-t border-border/40 p-3">
              <div className="flex items-end gap-2 rounded-2xl border border-border/50 bg-muted/30 px-3 py-2 focus-within:border-honey-500/60">
                <textarea
                  ref={inputRef}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={onKeyDown}
                  rows={1}
                  placeholder={
                    artifactId ? "Make it harder, shorter, focus on…" : "Ask about your material…"
                  }
                  className="max-h-24 flex-1 resize-none bg-transparent text-sm outline-none placeholder:opacity-40"
                />
                <button
                  onClick={() => void send(draft)}
                  disabled={!draft.trim() || sending}
                  className="rounded-xl bg-honey-500 p-2 text-bee-black transition disabled:opacity-30"
                  aria-label="Send message"
                >
                  {sending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <motion.button
        onClick={() => setOpen((value) => !value)}
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        className="fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-honey-500 text-bee-black shadow-2xl"
        aria-label={open ? "Close assistant" : "Open assistant"}
      >
        {open ? <X className="h-5 w-5" /> : <MessageCircle className="h-5 w-5" />}
      </motion.button>
    </>
  );
}
