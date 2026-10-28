#!/usr/bin/env node
// Pack-only validation. Uses the game's parser/ICU implementation without editing it.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseStringTableCsv, parseMessage } from '../../src/systems/textManager.js';
import { checkDraft } from '../translate.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const read = p => readFileSync(resolve(root, p), 'utf8').replace(/^\uFEFF/, '');
const args = process.argv.slice(2);
const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const enPath = option('--english', 'tools/ko/reference/app-v0.1.9050.en.csv');
const koPath = option('--korean', 'locales/ko/Port_Strings.csv');
const errors = [];

// Strict two-column format accepted by DFU: unquoted keys, quoted values, doubled quotes.
function table(path) {
  const raw = read(path), rows = [];
  let at = 0;
  const header = /^(?:Key,Value|Key,"Value")\r?\n/.exec(raw);
  if (!header) throw Error(path + ': invalid header');
  at = header[0].length;
  while (at < raw.length) {
    const row = /^([^",\r\n]+),"((?:[^"]|"")*)"(?:\r?\n|$)/.exec(raw.slice(at));
    if (!row) throw Error(path + ': malformed CSV near offset ' + at);
    rows.push([row[1], row[2].replaceAll('""', '"')]);
    at += row[0].length;
  }
  if (!rows.length) throw Error(path + ': empty catalogue');
  const runtime = parseStringTableCsv(raw);
  if (JSON.stringify(runtime) !== JSON.stringify(rows)) throw Error(path + ': game parser differs from strict CSV');
  const map = new Map();
  for (const [key, value] of rows) {
    if (map.has(key)) errors.push(key + ': duplicate in ' + path);
    if (!value.trim()) errors.push(key + ': empty in ' + path);
    map.set(key, value);
  }
  return map;
}

function argumentFormats(text) {
  const formats = new Set();
  const walk = nodes => {
    for (const node of nodes) if (typeof node === 'object' && node.arg) {
      formats.add(node.arg + ':' + (node.type ?? 'text') + ':' + (node.style ?? ''));
      if (node.options) for (const branch of node.options.values()) walk(branch);
    }
  };
  walk(parseMessage(text));
  return [...formats].sort().join('|');
}

try {
  const en = table(enPath), ko = table(koPath);
  const missing = [...en.keys()].filter(k => !ko.has(k));
  const extra = [...ko.keys()].filter(k => !en.has(k));
  errors.push(...missing.map(k => k + ': missing'), ...extra.map(k => k + ': extra'));
  const identical = [], noHangul = [], particleAlternatives = [], longText = [];
  for (const [key, english] of en) {
    const value = ko.get(key);
    if (value === undefined) continue;
    const problems = checkDraft(english, value, 'icu');
    errors.push(...problems.map(p => key + ': ' + p));
    if (!problems.length && argumentFormats(english) !== argumentFormats(value))
      errors.push(key + ': ICU argument type/number format changed');
    if (english === value) identical.push(key);
    if (!/[가-힣]/.test(value)) noHangul.push({ key, english, value });
    if (/\}\s*(?:을\(를\)|이\(가\)|은\(는\)|와\(과\)|\(으\)로)/.test(value)) particleAlternatives.push(key);
    // Heuristic only; actual overflow needs an in-game check.
    if (value.length > 180 || value.split('\n').some(s => s.length > 100))
      longText.push({ key, characters: value.length });
  }
  const report = { englishKeys: en.size, koreanKeys: ko.size, missing, extra, errors,
    identical, noHangul, particleAlternatives, longText,
    note: 'Identical tokens, units and proper names are review candidates, not automatically untranslated.' };
  const output = option('--report', null);
  if (output) writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ englishKeys: en.size, koreanKeys: ko.size,
    errors, identicalCandidates: identical.length, noHangulCandidates: noHangul.length,
    particleAlternatives: particleAlternatives.length, longTextCandidates: longText.length }, null, 2));
  if (errors.length) process.exitCode = 1;
} catch (err) { console.error(err.message); process.exitCode = 1; }
