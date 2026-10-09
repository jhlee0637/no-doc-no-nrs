import { expect, test } from '@playwright/test';
import {
  feedbackBulletItems, koreanJointLabel, translateFeedbackText,
} from '../src/ai-generated-feedback-text';

const joints = [
  ['WRIST', '손목'],
  ['THUMB_CMC', '엄지 손목 쪽 관절'],
  ['THUMB_MCP', '엄지 뿌리 관절'],
  ['THUMB_IP', '엄지 끝마디 관절'],
  ['THUMB_TIP', '엄지 끝'],
  ['INDEX_FINGER_MCP', '검지 뿌리 관절'],
  ['INDEX_FINGER_PIP', '검지 가운데 관절'],
  ['INDEX_FINGER_DIP', '검지 끝마디 관절'],
  ['INDEX_FINGER_TIP', '검지 끝'],
  ['MIDDLE_FINGER_MCP', '중지 뿌리 관절'],
  ['MIDDLE_FINGER_PIP', '중지 가운데 관절'],
  ['MIDDLE_FINGER_DIP', '중지 끝마디 관절'],
  ['MIDDLE_FINGER_TIP', '중지 끝'],
  ['RING_FINGER_MCP', '약지 뿌리 관절'],
  ['RING_FINGER_PIP', '약지 가운데 관절'],
  ['RING_FINGER_DIP', '약지 끝마디 관절'],
  ['RING_FINGER_TIP', '약지 끝'],
  ['PINKY_MCP', '새끼손가락 뿌리 관절'],
  ['PINKY_PIP', '새끼손가락 가운데 관절'],
  ['PINKY_DIP', '새끼손가락 끝마디 관절'],
  ['PINKY_TIP', '새끼손가락 끝'],
] as const;

test('all 21 joints have Korean labels, also in sentences and lowercase', () => {
  expect(joints).toHaveLength(21);
  for (const [code, label] of joints) {
    expect(koreanJointLabel(code)).toBe(label);
    expect(koreanJointLabel(code.toLowerCase())).toBe(label);
    expect(translateFeedbackText(`${code}를 확인해 주세요.`)).toBe(`${label}을 확인해 주세요.`);
  }
  expect(koreanJointLabel('PINKY_FINGER_PIP')).toBe('새끼손가락 가운데 관절');
});

test('unknown joints never invent a position and Korean labels are preserved', () => {
  expect(koreanJointLabel('')).toBe('관절 이름 확인 필요');
  expect(koreanJointLabel('UNRECOGNIZED_JOINT')).toBe('관절 이름 확인 필요');
  expect(koreanJointLabel('MIDDLE_FINGER_UNKNOWN')).toBe('중지 관절(이름 확인 필요)');
  expect(koreanJointLabel('constructor')).toBe('관절 이름 확인 필요');
  expect(koreanJointLabel(' 검지 가운데 관절 ')).toBe('검지 가운데 관절');
  expect(koreanJointLabel('예시 관절')).toBe('예시 관절');
  expect(koreanJointLabel('THUMB_22')).toBe('엄지 관절(이름 확인 필요)');
  expect(translateFeedbackText('MIDDLE_FINGER_UNKNOWN을 확인해 주세요.'))
    .toBe('중지 관절(이름 확인 필요)을 확인해 주세요.');
  expect(translateFeedbackText('THUMB_22를 확인해 주세요. WRIST_22도 확인하세요.'))
    .toBe('엄지 관절(이름 확인 필요)를 확인해 주세요. 관절 이름 확인 필요도 확인하세요.');
  expect(translateFeedbackText('NO_HAND_DETECTED와 request_state는 원문 코드입니다.'))
    .toBe('NO_HAND_DETECTED와 request_state는 원문 코드입니다.');
});

test('abbreviations and thumb IP translate without replacing parts of unrelated words', () => {
  expect(translateFeedbackText('엄지 IP 관절, THUMB(IP), MCP, PIP, DIP, CMC, TIP'))
    .toBe('엄지 끝마디 관절, 엄지 끝마디 관절, 뿌리 관절, 가운데 관절, 끝마디 관절, 손목 쪽 관절, 끝');
  expect(translateFeedbackText('shipping TIPTOP IP2는 그대로입니다.'))
    .toBe('shipping TIPTOP IP2는 그대로입니다.');
  expect(translateFeedbackText('thumb_ip와 Middle_Finger_Pip를 확인합니다.'))
    .toBe('엄지 끝마디 관절과 중지 가운데 관절을 확인합니다.');
  expect(translateFeedbackText('THUMB_TIP는 펴세요. WRIST가 보입니다. THUMB을 확인하세요.'))
    .toBe('엄지 끝은 펴세요. 손목이 보입니다. 엄지를 확인하세요.');
  expect(translateFeedbackText('THUMB_TIP가운데는 유지하세요. query_state는 원문입니다. 관절를 그대로 적었습니다.'))
    .toBe('엄지 끝가운데는 유지하세요. query_state는 원문입니다. 관절를 그대로 적었습니다.');
});

test('only identical parenthetical labels collapse; directions remain', () => {
  expect(translateFeedbackText('중지 가운데 관절(MIDDLE_FINGER_PIP)을 펴세요.'))
    .toBe('중지 가운데 관절을 펴세요.');
  expect(translateFeedbackText('MIDDLE_FINGER_PIP(중지 가운데 관절)을 펴세요.'))
    .toBe('중지 가운데 관절을 펴세요.');
  expect(translateFeedbackText('MIDDLE_FINGER_PIP(손등 방향)을 확인하세요.'))
    .toBe('중지 가운데 관절(손등 방향)을 확인하세요.');
  const translated = translateFeedbackText('THUMB_IP(엄지 끝마디 관절)을 펴지 마세요.');
  expect(translateFeedbackText(translated)).toBe(translated);
});

test('plain text preserves negation, decimals, signed values, and literal markup', () => {
  const text = '<img src=x onerror=alert(1)> MIDDLE_FINGER_PIP를 0.5cm 더 굽히지 마세요. -0.25는 유지하세요.';
  expect(translateFeedbackText(text))
    .toBe('<img src=x onerror=alert(1)> 중지 가운데 관절을 0.5cm 더 굽히지 마세요. -0.25는 유지하세요.');
  expect(translateFeedbackText('이미 올바르다고 판단하지 않았습니다.')).toBe('이미 올바르다고 판단하지 않았습니다.');
});

test('bullets preserve sentences, numbers, abbreviations, and order while cleaning markers', () => {
  expect(feedbackBulletItems('1. MIDDLE_FINGER_PIP를 0.5cm 펴세요. 더 굽히지 마세요.\n\n• THUMB_IP를 확인하세요!\n- 손목은 유지하세요.'))
    .toEqual(['중지 가운데 관절을 0.5cm 펴세요.', '더 굽히지 마세요.', '엄지 끝마디 관절을 확인하세요!', '손목은 유지하세요.']);
  expect(feedbackBulletItems('e.g. 0.5cm 안내입니다. -0.25는 변경하지 마세요.\n* 다음 안내\n2) 마지막 안내'))
    .toEqual(['e.g. 0.5cm 안내입니다.', '-0.25는 변경하지 마세요.', '다음 안내', '마지막 안내']);
  expect(feedbackBulletItems('사진을 다시 찍으세요.손목이 보이나요? 네!'))
    .toEqual(['사진을 다시 찍으세요.', '손목이 보이나요?', '네!']);
  expect(feedbackBulletItems(' \n\n')).toEqual([]);
});
