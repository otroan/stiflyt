#!/usr/bin/env node
/**
 * Quick JSX structure validator
 * Checks for matching opening/closing tags and fragments
 */

const fs = require('fs');
const path = require('path');

const filePath = process.argv[2] || path.join(__dirname, 'src/components/InfoPanel.tsx');

console.log(`Validating JSX structure in: ${filePath}\n`);

const content = fs.readFileSync(filePath, 'utf8');
const lines = content.split('\n');

// Track fragment and conditional nesting
const stack = [];
const errors = [];

for (let i = 0; i < lines.length; i++) {
  const line = lines[i];
  const lineNum = i + 1;
  
  // Check for opening fragments <>
  const openFragMatch = line.match(/<>/g);
  if (openFragMatch) {
    openFragMatch.forEach(() => {
      stack.push({ type: 'fragment', line: lineNum, char: 'open' });
    });
  }
  
  // Check for closing fragments </>
  const closeFragMatch = line.match(/<\/>/g);
  if (closeFragMatch) {
    closeFragMatch.forEach(() => {
      const last = stack.pop();
      if (!last || last.type !== 'fragment') {
        errors.push({
          line: lineNum,
          message: `Unexpected closing fragment </> - no matching opening fragment`,
          context: line.trim()
        });
      }
    });
  }
  
  // Check for opening conditionals {condition && (
  const openCondMatch = line.match(/\{[^}]*&&\s*\(/g);
  if (openCondMatch) {
    openCondMatch.forEach(() => {
      stack.push({ type: 'conditional', line: lineNum, char: 'open' });
    });
  }
  
  // Check for closing conditionals )}
  const closeCondMatch = line.match(/\)\s*\}/g);
  if (closeCondMatch) {
    closeCondMatch.forEach(() => {
      const last = stack.pop();
      if (!last || last.type !== 'conditional') {
        errors.push({
          line: lineNum,
          message: `Unexpected closing conditional )} - no matching opening conditional`,
          context: line.trim()
        });
      }
    });
  }
  
  // Check for opening JSX tags <div, <span, etc (simple check)
  const openTagMatch = line.match(/<([a-zA-Z][a-zA-Z0-9]*)[^>]*>/g);
  if (openTagMatch) {
    openTagMatch.forEach(match => {
      const selfClosing = match.endsWith('/>');
      if (!selfClosing) {
        const tagName = match.match(/<([a-zA-Z][a-zA-Z0-9]*)/)?.[1];
        if (tagName) {
          stack.push({ type: 'tag', name: tagName, line: lineNum });
        }
      }
    });
  }
  
  // Check for closing JSX tags </div>, </span, etc
  const closeTagMatch = line.match(/<\/([a-zA-Z][a-zA-Z0-9]*)>/g);
  if (closeTagMatch) {
    closeTagMatch.forEach(match => {
      const tagName = match.match(/<\/([a-zA-Z][a-zA-Z0-9]*)>/)?.[1];
      if (tagName) {
        const last = stack.pop();
        if (!last || last.type !== 'tag' || last.name !== tagName) {
          errors.push({
            line: lineNum,
            message: `Unexpected closing tag </${tagName}> - expected ${last ? `${last.type} ${last.name || ''}` : 'nothing'}`,
            context: line.trim()
          });
        }
      }
    });
  }
}

// Check for unclosed items
if (stack.length > 0) {
  stack.forEach(item => {
    errors.push({
      line: item.line,
      message: `Unclosed ${item.type}${item.name ? ` (${item.name})` : ''} opened at line ${item.line}`,
      context: lines[item.line - 1]?.trim() || 'unknown'
    });
  });
}

// Report results
if (errors.length === 0) {
  console.log('✅ No JSX structure errors found!');
  process.exit(0);
} else {
  console.log(`❌ Found ${errors.length} JSX structure error(s):\n`);
  errors.forEach((error, idx) => {
    console.log(`${idx + 1}. Line ${error.line}: ${error.message}`);
    console.log(`   Context: ${error.context.substring(0, 80)}${error.context.length > 80 ? '...' : ''}\n`);
  });
  process.exit(1);
}
