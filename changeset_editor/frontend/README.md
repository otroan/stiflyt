# Changeset Editor Frontend

React + TypeScript frontend for editing route segments with event sourcing, validation, and GitHub PR integration.

## Tech Stack

- **React 18** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool and dev server
- **Leaflet** - Map rendering
- **React-Leaflet** - React bindings for Leaflet
- **Geoman** - Drawing and editing tools for Leaflet
- **RBush** - Spatial indexing for snap targets

## Prerequisites

- **Node.js 20+** (or 18+)
- **npm** or **yarn** or **pnpm**

## Installation

1. **Install dependencies**:
```bash
npm install
```

## Development

### Start Development Server

```bash
npm run dev
```

The application will be available at: **http://localhost:3000**

### Development Server Features

- **Hot Module Replacement (HMR)** - Changes reflect immediately
- **API Proxy** - `/api` requests are proxied to `http://127.0.0.1:8001` (configured in `vite.config.ts`)
- **TypeScript** - Full type checking and IntelliSense support

### Environment Variables

Create a `.env` file in the frontend directory (see `.env.example`):

```bash
# API Base URL (optional, defaults to /api)
VITE_API_BASE=/api
```

**Note**: All Vite environment variables must be prefixed with `VITE_`

### Development Workflow

1. Start the backend API server (see parent README.md)
2. Start the frontend dev server: `npm run dev`
3. Open http://localhost:3000 in your browser
4. Make changes to source files - they will hot-reload automatically

## Building for Production

### Build

```bash
npm run build
```

This will:
1. Run TypeScript type checking (`tsc`)
2. Build optimized production bundle with Vite
3. Output files to `dist/` directory

### Preview Production Build

```bash
npm run preview
```

This serves the production build locally for testing.

## Project Structure

```
frontend/
├── src/
│   ├── api/
│   │   └── client.ts          # API client with request helpers
│   ├── components/
│   │   ├── MapView.tsx        # Main map component with Leaflet
│   │   ├── RouteSelector.tsx  # Route search and selection
│   │   └── SidePanel.tsx      # Changeset info and actions
│   ├── utils/
│   │   └── snap.ts           # Snap target utilities
│   ├── types.ts               # TypeScript type definitions
│   ├── App.tsx                # Main application component
│   ├── App.css                # Application styles
│   └── main.tsx               # Application entry point
├── index.html                 # HTML template
├── package.json               # Dependencies and scripts
├── tsconfig.json              # TypeScript config for source files
├── tsconfig.node.json         # TypeScript config for Vite config
├── vite.config.ts             # Vite configuration
├── .env.example               # Environment variables template
└── README.md                  # This file
```

## Available Scripts

- `npm run dev` - Start development server with HMR
- `npm run build` - Build for production (type checks + bundle)
- `npm run preview` - Preview production build locally

## Configuration

### TypeScript

- **Source files**: `tsconfig.json` - Strict mode enabled, includes `src/` directory
- **Config files**: `tsconfig.node.json` - For `vite.config.ts` and other Node.js files

### Vite

Configuration in `vite.config.ts`:
- **Port**: 3000 (development server)
- **Proxy**: `/api` → `http://127.0.0.1:8001` (backend API)
- **Aliases**: `@/*` → `./src/*` (for cleaner imports)
- **Optimizations**: Geoman library pre-bundled

### API Client

The API client (`src/api/client.ts`) uses:
- Base URL from `VITE_API_BASE` environment variable (defaults to `/api`)
- `X-User` header for user identification (from `localStorage.getItem('user')`)

## Development Tips

### Import Aliases

Use the `@/` alias for cleaner imports:

```typescript
// Instead of: import { api } from '../../../api/client'
import { api } from '@/api/client'
```

### Type Safety

- All API responses are typed (see `src/types.ts`)
- TypeScript strict mode is enabled
- Unused variables/parameters are errors (helps keep code clean)

### Map Development

- Leaflet map is initialized in `MapView.tsx`
- Geoman is loaded dynamically to avoid SSR issues
- Snap targets use RBush for efficient spatial queries

## Troubleshooting

### Port Already in Use

If port 3000 is already in use:
```bash
npm run dev -- --port 3001
```

### API Connection Issues

1. Verify backend is running on `http://127.0.0.1:8001`
2. Check Vite proxy configuration in `vite.config.ts`
3. For production, set `VITE_API_BASE` to your API URL

### Type Errors

Run TypeScript type checking:
```bash
npx tsc --noEmit
```

### Build Errors

1. Check for TypeScript errors first
2. Verify all dependencies are installed: `npm install`
3. Clear node_modules and reinstall if needed: `rm -rf node_modules && npm install`

## Code Style

- **TypeScript**: Strict mode, prefer explicit types
- **React**: Functional components with hooks
- **Imports**: Use `@/` alias for src imports
- **Error Handling**: Use try/catch, display user-friendly messages (TODO: replace alerts)

## Future Improvements

See `TASK_LIST.md` for detailed task list. Key areas:
- Error handling system (replace alerts/console.error)
- Header-based layout redesign
- Metadata editing UI
- Route validation error display
- Local changeset export/import

## License

[Your License Here]
