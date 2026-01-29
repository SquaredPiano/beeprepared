# ==============================================================================
# BeePrepared Frontend Dockerfile (Production Build)
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Dependency Installation & Build
# ------------------------------------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies (cached)
COPY package.json package-lock.json* ./
RUN npm ci

# Copy source code
COPY . .

# Build the Next.js application
# We accept build arguments for public env vars if strictly needed at build time,
# though runtime vars are preferred via NEXT_PUBLIC injection.
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ------------------------------------------------------------------------------
# Stage 2: Production Runtime
# ------------------------------------------------------------------------------
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Create non-root user for security
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy built assets from builder stage
# Standard Next.js standalone build structure
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

# Switch to non-root user
USER nextjs

# Expose the application port
EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Start the server
CMD ["node", "server.js"]
