import path from "node:path";

// Husky's pre-commit runs `npx lint-staged` from the repo root, but the frontend
// toolchain (eslint, prettier) lives in frontend/node_modules and ESLint's flat
// config (frontend/eslint.config.js) is only discovered from the frontend cwd.
// So frontend files must be linted from inside frontend/ against paths made
// relative to it; `npx --no-install` resolves the local bins without a network
// hit. Backend files run ruff by bare name (the commit hook expects the venv on
// PATH — see the project's git-hooks/venv note).
const frontendRelative = (files) =>
  files.map((file) => path.relative("frontend", file)).join(" ");

export default {
  "frontend/**/*.{ts,tsx}": (files) => {
    const rel = frontendRelative(files);
    return [
      `cd frontend && npx --no-install eslint --fix ${rel}`,
      `cd frontend && npx --no-install prettier --write ${rel}`,
    ];
  },
  "backend/**/*.py": ["ruff check --fix", "ruff format"],
};
