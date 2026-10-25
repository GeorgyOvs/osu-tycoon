/** Russian strings for the hints feature. Merged into RU / RU_PATTERNS in i18n.ru.ts. */

type Out = string | ((...groups: string[]) => string)

export const RU_HINTS: Record<string, string> = {
  'How precisely you can read maps: grows with plays, matches and skill': 'Насколько точно вы читаете карты: растёт с игрой, матчами и навыком',
  Read: 'Чтение',
  'Mainly tests': 'В основном проверяет',
  'needed: pass / comfortable · you': 'нужно: пройти / комфортно · вы',
  'Reading the map…': 'Изучаю карту…',
}

export const RU_HINTS_PATTERNS: [RegExp, Out][] = []
