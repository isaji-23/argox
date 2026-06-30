import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    rules: {
      // We intentionally co-locate small constants/hooks next to components
      // (ICON_PATHS, MODEL_COLORS, useShell); fast-refresh granularity is a
      // non-goal here.
      'react-refresh/only-export-components': 'off',
      // Standard derive-from-prop / debounce / load-on-mount effects set state
      // synchronously; this brand-new rule flags those legitimate patterns.
      'react-hooks/set-state-in-effect': 'off',
    },
  },
])
