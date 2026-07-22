import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import jsxA11y from "eslint-plugin-jsx-a11y";
import prettier from "eslint-config-prettier";

export default tseslint.config(
  // `public/` holds static, hand-written browser assets (service worker) that
  // aren't part of the TS app build and have their own global scope — not linted.
  { ignores: ["dist", "node_modules", "public", "*.config.js", "*.config.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
      "jsx-a11y": jsxA11y,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.flatConfigs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      // The auth effects deliberately call setState inside a StrictMode-guarded,
      // run-once effect (see useAuth/VerifyRoute comments). Keep this visible as
      // a warning rather than a hard error that blocks those intentional patterns.
      "react-hooks/set-state-in-effect": "warn",
    },
  },
  prettier,
);
