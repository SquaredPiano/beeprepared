## Project Summary
BeePrepared is an intentional knowledge architecture platform designed to transform educational artifacts (PDFs, audio, video) into high-fidelity study materials. It uses a multi-layer cognitive pipeline to extract, categorize, and synthesize information into structured knowledge artifacts.

## Tech Stack
- **Framework**: Next.js 16.1 (React 19.2) with App Router & Turbopack
- **Styling**: Tailwind CSS 4.0 (JIT)
- **Animations**: GSAP 3.14 (Complex timelines), Framer Motion 11.15 (Transitions)
- **State Management**: Zustand 5.0 (Global app state), TanStack Query v5.62 (Server state & Polling)
- **Visualization**: React Flow (@xyflow/react) for pipeline transparency
- **Infrastructure**: Vercel Edge Network

## Architecture
- **App Router**: RSC-first architecture with minimal client-side bailouts.
- **Hexagonal Processing**: Multi-stage data processing pipeline visualized in real-time.
- **Minimalist Design**: High-fidelity, intentional UI using "Instrument Sans" and "Instrument Serif" typography.
- **Zustand Store**: Centralized state for ingestion and processing tasks.

## User Preferences
- **Design Aesthetic**: Minimalist, senior frontend principles, intentional typography.
- **Color Palette**: Bee-themed (Honey, Bee Black, Cream, Wax) with high contrast.
- **Animation Style**: Smooth GSAP timelines, no jarring transitions, functional motion.
- **Accessibility**: WCAG 2.1 AA compliance, ARIA labels, keyboard navigation.
- **Tone**: Professional, architectural, no emojis in UI code.

## Project Guidelines
- **No AI Slop**: Avoid generic gradients, overused components, and clichéd layouts.
- **Strict TypeScript**: 5.7+ with strict mode enabled.
- **Functional Components**: Named exports preferred.
- **Modern Patterns**: Use TanStack Query for polling instead of manual intervals.
- **Clean Dependencies**: Keep bundle size optimized and dependencies minimal.

## Common Patterns
- **Ingestion Pipeline**: Ingest -> Extract -> Categorize -> Generate -> Finalize.
- **Worker Nodes**: Custom React Flow nodes representing distinct processing units.
- **Honey Jar Progress**: SVG-based animated fill representing collective task completion.
