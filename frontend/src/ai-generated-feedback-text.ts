const jointLabels: Readonly<Record<string, string>> = {
  WRIST: '손목',
  THUMB_CMC: '엄지 손목 쪽 관절',
  THUMB_MCP: '엄지 뿌리 관절',
  THUMB_IP: '엄지 끝마디 관절',
  THUMB_TIP: '엄지 끝',
  INDEX_FINGER_MCP: '검지 뿌리 관절',
  INDEX_FINGER_PIP: '검지 가운데 관절',
  INDEX_FINGER_DIP: '검지 끝마디 관절',
  INDEX_FINGER_TIP: '검지 끝',
  MIDDLE_FINGER_MCP: '중지 뿌리 관절',
  MIDDLE_FINGER_PIP: '중지 가운데 관절',
  MIDDLE_FINGER_DIP: '중지 끝마디 관절',
  MIDDLE_FINGER_TIP: '중지 끝',
  RING_FINGER_MCP: '약지 뿌리 관절',
  RING_FINGER_PIP: '약지 가운데 관절',
  RING_FINGER_DIP: '약지 끝마디 관절',
  RING_FINGER_TIP: '약지 끝',
  PINKY_MCP: '새끼손가락 뿌리 관절',
  PINKY_PIP: '새끼손가락 가운데 관절',
  PINKY_DIP: '새끼손가락 끝마디 관절',
  PINKY_TIP: '새끼손가락 끝',
};

const wordLabels: Readonly<Record<string, string>> = {
  THUMB: '엄지', INDEX_FINGER: '검지', MIDDLE_FINGER: '중지',
  RING_FINGER: '약지', PINKY_FINGER: '새끼손가락', PINKY: '새끼손가락',
  INDEX: '검지', MIDDLE: '중지', RING: '약지', FINGER: '손가락',
  CMC: '손목 쪽 관절', MCP: '뿌리 관절', PIP: '가운데 관절',
  DIP: '끝마디 관절', IP: '마디 사이 관절', TIP: '끝',
};

const unknownJoint = '관절 이름 확인 필요';
const fingerPrefixes: Readonly<Record<string, string>> = {
  THUMB: '엄지', INDEX_FINGER: '검지', MIDDLE_FINGER: '중지',
  RING_FINGER: '약지', PINKY_FINGER: '새끼손가락', PINKY: '새끼손가락',
};

function knownLabel(token: string): string | undefined {
  const normalized = token.toUpperCase().replace(/^PINKY_FINGER_/, 'PINKY_');
  return Object.hasOwn(jointLabels, normalized) ? jointLabels[normalized]
    : Object.hasOwn(wordLabels, normalized) ? wordLabels[normalized] : undefined;
}

function unknownCodeLabel(token: string): string | undefined {
  const normalized = token.toUpperCase();
  for (const [prefix, finger] of Object.entries(fingerPrefixes)) {
    if (normalized.startsWith(`${prefix}_`)) return `${finger} 관절(이름 확인 필요)`;
  }
  if (/^WRIST_/i.test(token)) return unknownJoint;
  return undefined;
}

/** Unknown labels never infer a joint position; already Korean labels remain readable. */
export function koreanJointLabel(code: string): string {
  const value = code.trim();
  return knownLabel(value) ?? unknownCodeLabel(value)
    ?? (/[가-힣]/.test(value) && !/[A-Za-z]/.test(value) ? value : unknownJoint);
}

function escapePattern(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function labelParticle(label: string, particle: string): string {
  const finalSyllable = label.charCodeAt(label.length - 1);
  const hasFinalConsonant = finalSyllable >= 0xac00 && finalSyllable <= 0xd7a3
    && (finalSyllable - 0xac00) % 28 !== 0;
  const pairs = ['을를', '은는', '과와', '이가'];
  const pair = pairs.find((candidate) => candidate.includes(particle));
  return pair ? pair[hasFinalConsonant ? 0 : 1] : particle;
}

/** Returns plain text. Rendering must use textContent or text nodes. */
export function translateFeedbackText(text: string): string {
  // Match particles only directly after a known code and at their own word boundary.
  // A following Korean word such as "가운데" must never be treated as the particle "가".
  let result = text.replace(/(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*)(?![A-Za-z0-9_])(?:([을를은는과와이가])(?=$|[^가-힣A-Za-z0-9_]))?/g,
    (_match, token: string, particle: string | undefined) => {
      const label = knownLabel(token);
      if (label) return label + (particle ? labelParticle(label, particle) : '');
      return (unknownCodeLabel(token) ?? token) + (particle ?? '');
    });
  // IP is the thumb's single interphalangeal joint when the thumb is explicit.
  result = result.replace(/엄지(?:\s*손가락)?\s*(?:\(\s*마디 사이 관절\s*\)|마디 사이 관절)(?:\s*관절)?/g,
    '엄지 끝마디 관절');
  result = result.replace(/관절\s+관절/g, '관절');
  // Only remove parentheses that repeat precisely the same known label.
  const labels = [...new Set([...Object.values(jointLabels), ...Object.values(wordLabels)])]
    .sort((left, right) => right.length - left.length);
  for (const label of labels) {
    const literal = escapePattern(label);
    result = result.replace(new RegExp(`${literal}\\s*[（(]\\s*${literal}\\s*[）)]`, 'g'), label);
  }
  return result;
}

const abbreviation = /(?:\b(?:e\.g|i\.e|etc|vs|dr|mr|mrs|ms|prof|approx|fig|no)|\b[A-Za-z])\.$/i;

function splitSentences(line: string): string[] {
  const items: string[] = [];
  let start = 0;
  for (let index = 0; index < line.length; index += 1) {
    const punctuation = line[index];
    if (!'.!?。！？'.includes(punctuation)) continue;
    const next = line[index + 1];
    if (punctuation === '.') {
      if (/\d/.test(line[index - 1] ?? '') && /\d/.test(next ?? '')) continue;
      if (abbreviation.test(line.slice(start, index + 1))) continue;
    }
    if (next && !/\s|[가-힣]/.test(next)) continue;
    const item = line.slice(start, index + 1).trim();
    if (item) items.push(item);
    start = index + 1;
  }
  const remaining = line.slice(start).trim();
  if (remaining) items.push(remaining);
  return items;
}

/** Keeps sentence order, punctuation, numerical values, and negative statements. */
export function feedbackBulletItems(text: string): string[] {
  return translateFeedbackText(text).split(/\r?\n/).flatMap((line) => {
    const withoutMarker = line.trim().replace(/^(?:[-*•]\s+|\d+[.)]\s+)/, '');
    return splitSentences(withoutMarker);
  });
}
