# Proteomics CoPYlot Frontend

The frontend is a React 19, TypeScript, Vite, and Tailwind application. It communicates with FastAPI through `src/lib/api.ts`.

## Commands

```bash
npm install
npm run dev
npm run build
npm run lint
```

The development launchers under `../packaging/<platform>/` set the normal application/viewer/AI mode variables and proxy target.

## Organization

- `src/features/`: domain-specific screens and workflows.
- `src/components/`: shared UI and application shell components.
- `src/lib/`: API transport, shared types, settings, and browser-state helpers.
- `public/`: runtime assets and generated user manuals.

Add feature code to the closest domain and avoid growing `App.tsx` or `src/lib/api.ts` when a new module has clear standalone ownership.
