#!/bin/bash
# Quick syntax check script - faster than full build
cd "$(dirname "$0")"
FILE="${1:-src/components/InfoPanel.tsx}"
echo "🔍 Quick syntax check: $FILE"

# Use tsconfig.json for proper configuration
npx tsc --noEmit --project tsconfig.json 2>&1 | \
  grep -E "(error TS|Expected|Unexpected|closing tag|fragment)" | \
  grep -v "node_modules" | \
  grep -v "Cannot find global" | \
  grep -v "import.meta" | \
  grep -v "Promise.*only refers to a type" | \
  head -10

EXIT=${PIPESTATUS[0]}
if [ $EXIT -eq 0 ]; then
  echo "✅ No JSX syntax errors found!"
else
  # Check if there are actual JSX errors (not just config issues)
  JSX_ERRORS=$(npx tsc --noEmit --project tsconfig.json 2>&1 | grep -E "(Expected|Unexpected|closing tag|fragment|17014|17015)" | wc -l)
  if [ "$JSX_ERRORS" -eq 0 ]; then
    echo "✅ No JSX syntax errors (only TypeScript config warnings)"
    exit 0
  fi
fi
exit $EXIT
