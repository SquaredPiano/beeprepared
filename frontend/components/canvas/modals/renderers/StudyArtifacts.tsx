"use client";

import { ChevronRight, Clock, ListChecks } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { cn } from "@/lib/utils";

/**
 * Renderers for the artifact types added alongside the flow engine.
 *
 * They live here rather than in ArtifactPreviewModal so that file stays a
 * dispatcher instead of growing another few hundred lines per type.
 */

const MARKDOWN_PLUGINS = {
  remarkPlugins: [remarkGfm, remarkMath],
  rehypePlugins: [rehypeKatex],
};

// --- Study guide -----------------------------------------------------------

interface StudyGuideData {
  title?: string;
  estimated_minutes?: number;
  objectives?: string[];
  body?: string;
  checklist?: string[];
}

export function StudyGuideRenderer({ data }: { data: StudyGuideData }) {
  // Checking off items is deliberately local state: this is a working aid
  // during a study session, not something worth a write to the artifact.
  const [checked, setChecked] = useState<Set<number>>(new Set());

  const toggle = (index: number) =>
    setChecked((previous) => {
      const next = new Set(previous);
      next.has(index) ? next.delete(index) : next.add(index);
      return next;
    });

  if (!data?.body && !data?.objectives?.length) {
    return <EmptyState label="study guide" />;
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-wax bg-gradient-to-br from-sky-50 to-white p-6">
        <h2 className="text-xl font-semibold">{data.title || "Study Guide"}</h2>
        {data.estimated_minutes ? (
          <p className="mt-2 flex items-center gap-1.5 text-sm opacity-60">
            <Clock className="h-3.5 w-3.5" />
            About {data.estimated_minutes} minutes
          </p>
        ) : null}

        {data.objectives?.length ? (
          <ol className="mt-4 space-y-1.5">
            {data.objectives.map((objective, index) => (
              <li key={index} className="flex gap-2.5 text-sm">
                <span className="font-mono text-xs opacity-40">{index + 1}.</span>
                <span>{objective}</span>
              </li>
            ))}
          </ol>
        ) : null}
      </header>

      {data.body ? (
        <article className="prose prose-sm max-w-none rounded-2xl border border-wax bg-white p-6">
          <ReactMarkdown {...MARKDOWN_PLUGINS}>{data.body}</ReactMarkdown>
        </article>
      ) : null}

      {data.checklist?.length ? (
        <section className="rounded-2xl border border-wax bg-white p-6">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <ListChecks className="h-4 w-4" />
            Can you answer these?
          </h3>
          <ul className="space-y-2">
            {data.checklist.map((item, index) => (
              <li key={index}>
                <button
                  onClick={() => toggle(index)}
                  className="flex w-full items-start gap-3 rounded-lg p-2 text-left text-sm transition hover:bg-cream"
                >
                  <span
                    className={cn(
                      "mt-0.5 flex h-4 w-4 flex-none items-center justify-center rounded border transition",
                      checked.has(index)
                        ? "border-sky-500 bg-sky-500 text-white"
                        : "border-wax",
                    )}
                  >
                    {checked.has(index) ? "✓" : ""}
                  </span>
                  <span className={cn(checked.has(index) && "line-through opacity-50")}>
                    {item}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

// --- Cheat sheet -----------------------------------------------------------

interface CheatSheetData {
  title?: string;
  sections?: { heading?: string; entries?: string[] }[];
}

export function CheatSheetRenderer({ data }: { data: CheatSheetData }) {
  if (!data?.sections?.length) return <EmptyState label="cheat sheet" />;

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">{data.title || "Cheat Sheet"}</h2>

      {/* Two columns: the point of a cheat sheet is density, and this is how it
          would be laid out on paper. Collapses to one column on narrow screens. */}
      <div className="columns-1 gap-4 md:columns-2 [&>*]:mb-4 [&>*]:break-inside-avoid">
        {data.sections.map((section, index) => (
          <section key={index} className="rounded-xl border border-wax bg-white p-4">
            <h3 className="mb-2 border-b border-wax pb-1.5 text-xs font-bold uppercase tracking-wider text-teal-600">
              {section.heading}
            </h3>
            <ul className="space-y-1.5">
              {(section.entries ?? []).map((entry, entryIndex) => (
                <li key={entryIndex} className="flex gap-2 text-[13px] leading-snug">
                  <span className="select-none text-teal-500">▸</span>
                  <span className="prose prose-sm max-w-none">
                    <ReactMarkdown {...MARKDOWN_PLUGINS}>{entry}</ReactMarkdown>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

// --- Mind map --------------------------------------------------------------

interface MindMapNode {
  label?: string;
  detail?: string;
  children?: MindMapNode[];
}

interface MindMapData {
  title?: string;
  root?: MindMapNode;
}

function MindMapBranch({ node, depth }: { node: MindMapNode; depth: number }) {
  // Top two levels start open; leaves are collapsed so the map reads as a
  // summary first and drills down on demand.
  const [open, setOpen] = useState(depth < 2);
  const hasChildren = Boolean(node.children?.length);

  const accents = [
    "border-fuchsia-400 bg-fuchsia-50",
    "border-violet-300 bg-violet-50/60",
    "border-slate-200 bg-white",
  ];

  return (
    <div className={cn(depth > 0 && "ml-4 border-l border-dashed border-wax pl-4")}>
      <button
        onClick={() => hasChildren && setOpen((value) => !value)}
        className={cn(
          "my-1 flex w-full items-start gap-2 rounded-xl border px-3 py-2 text-left transition",
          accents[Math.min(depth, accents.length - 1)],
          hasChildren && "hover:shadow-sm",
        )}
      >
        {hasChildren ? (
          <ChevronRight
            className={cn("mt-0.5 h-4 w-4 flex-none transition-transform", open && "rotate-90")}
          />
        ) : (
          <span className="mt-2 h-1.5 w-1.5 flex-none rounded-full bg-slate-300" />
        )}
        <span>
          <span className={cn("text-sm", depth === 0 ? "font-semibold" : "font-medium")}>
            {node.label}
          </span>
          {node.detail ? (
            <span className="mt-0.5 block text-xs opacity-60">{node.detail}</span>
          ) : null}
        </span>
      </button>

      {open && hasChildren
        ? node.children!.map((child, index) => (
            <MindMapBranch key={index} node={child} depth={depth + 1} />
          ))
        : null}
    </div>
  );
}

export function MindMapRenderer({ data }: { data: MindMapData }) {
  if (!data?.root) return <EmptyState label="mind map" />;

  return (
    <div className="space-y-3">
      <h2 className="text-xl font-semibold">{data.title || "Mind Map"}</h2>
      <div className="rounded-2xl border border-wax bg-white p-4">
        <MindMapBranch node={data.root} depth={0} />
      </div>
    </div>
  );
}

// --- Shared ----------------------------------------------------------------

function EmptyState({ label }: { label: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-wax p-10 text-center text-sm opacity-50">
      This {label} has no content yet. Try regenerating it.
    </div>
  );
}
