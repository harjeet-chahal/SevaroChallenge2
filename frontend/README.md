# Sevaro Pulse — frontend

Next.js (App Router) + TypeScript + Tailwind CSS v4 + shadcn/ui + Lucide + Recharts.

```bash
cp .env.example .env.local   # point NEXT_PUBLIC_API_BASE_URL at the backend
npm install
npm run dev                  # http://localhost:3000
npm run lint
npm run build
```

- Routes: `/` role picker, `/coordinator`, `/clinical-lead`, `/physician`.
- Add shadcn components with `npx shadcn@latest add <name>`. They land in `src/components/ui/`.
- API types in `src/lib/api/types.ts` mirror `backend/app/schemas`. The backend is the
  source of truth, so update the mirrors when schemas change.
- Next.js 16 has breaking changes from earlier versions. Check `node_modules/next/dist/docs/`
  (see `AGENTS.md`) before relying on older patterns.

See the root [README](../README.md) and [docs/architecture.md](../docs/architecture.md).
