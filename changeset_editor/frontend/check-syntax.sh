#!/bin/bash
# Quick syntax checker for React/TypeScript files
# Usage: ./check-syntax.sh [file]

FILE="${1:-src/components/InfoPanel.tsx}"

echo "🔍 Checking syntax for: $FILE"
echo ""

# Use TypeScript compiler to check syntax
cd "$(dirname "$0")"

# Check if file exists
if [ ! -f "$FILE" ]; then
  echo "❌ File not found: $FILE"
  exit 1
fi

# Run TypeScript compiler in check mode
npx tsc --noEmit --jsx react-jsx --skipLibCheck "$FILE" 2>&1 | \
  grep -E "(error TS|Expected|Unexpected|closing tag)" | \
  head -20

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
  echo ""
  echo "✅ No syntax errors found!"
else
  echo ""
  echo "❌ Syntax errors detected. Run 'npm run build' for full details."
fi

exit $EXIT_CODE
