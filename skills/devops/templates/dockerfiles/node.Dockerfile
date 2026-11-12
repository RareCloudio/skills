# Node.js app with a build step (TypeScript, a bundler, a framework's server build) and an npm
# lockfile. Copy to the project root as `Dockerfile`, next to the `.dockerignore` template.
#
# Placeholders (sample values in brackets, used when this file is checked):
#   <NODE_VERSION>  the Node.js major line the project runs on; the image's publisher
#                   rebuilds that tag with security fixes, an exact version tag is frozen
#                   once the next one ships (references/first-deploy.md, "Image tags") [24]
#   <PORT>          port the app listens on inside the container [3000]
#   <HEALTH_PATH>   path that answers 200 when the app can serve [/healthz]
#   <START_FILE>    built entry point, relative to /app [dist/server.js]
#
# For pnpm or Yarn: copy that lockfile instead and run `corepack enable` before installing.
# If the app ignores SIGTERM, `docker stop` waits 10 s and kills it: handle SIGTERM in the app
# or run the container with `init: true` (Compose) / `--init` (docker run).

FROM node:<NODE_VERSION>-trixie-slim AS build
WORKDIR /app
# Only the manifests first, so the install layer is reused until a dependency changes.
COPY package.json package-lock.json ./
# Every dependency, dev ones included: the build step below needs them (tsc, bundlers).
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY . .
# Build, then drop the dev dependencies from node_modules before it is copied on.
RUN npm run build && npm prune --omit=dev

FROM node:<NODE_VERSION>-trixie-slim
ENV NODE_ENV=production \
    PORT=<PORT>
WORKDIR /app
# Files stay owned by root, so the app (running as `node`) cannot rewrite its own code.
COPY --from=build /app/package.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
USER node
EXPOSE <PORT>
# The slim image has no curl; Node's built-in fetch does the probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:<PORT><HEALTH_PATH>').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
# Exec form: node is PID 1 and receives the stop signal itself (`npm start` would sit between).
CMD ["node", "<START_FILE>"]
