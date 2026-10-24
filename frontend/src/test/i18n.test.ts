import { describe, expect, it } from 'vitest'
import { STAT_LABELS, DRILL_LABELS, GROUP_LABELS, PRESET_LABELS } from '../i18n.keys'
import { RU } from '../i18n.ru'
import { getLang, setLang, t, tx } from '../i18n'

const sources = import.meta.glob(['../components/*.tsx', '../App.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<
  string,
  string
>

function keysUsed(): Set<string> {
  const keys = new Set<string>()
  const pat = /\bt\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")/g
  for (const src of Object.values(sources)) {
    for (const m of src.matchAll(pat)) keys.add((m[1] ?? m[2]).replace(/\\'/g, "'"))
  }
  return keys
}

describe('Russian translation', () => {
  it('covers every interface string', () => {
    const missing = [...keysUsed()].filter((k) => !(k in RU))
    expect(missing).toEqual([])
  })

  it('covers backend labels that arrive by key', () => {
    const labels = [STAT_LABELS, DRILL_LABELS, GROUP_LABELS, PRESET_LABELS].flatMap((m) => Object.values(m))
    expect(labels.filter((l) => !(l in RU))).toEqual([])
  })

  it('keeps placeholders intact', () => {
    for (const [en, ru] of Object.entries(RU)) {
      const names = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()
      expect(names(ru), en).toEqual(names(en))
    }
  })

  it('translates backend messages by template', () => {
    const before = getLang()
    setLang('ru', false)
    try {
      expect(tx('Something clicked: Snap Aim +1.4.')).toBe('Что-то щёлкнуло: Снэп-аим (рывки) +1.4.')
      expect(tx('Sponsorship deal pays $1,200 this month.')).toBe('Спонсорский контракт: $1,200 в этом месяце.')
      expect(tx('Round of 16')).toBe('1/8 финала')
      expect(tx('5th–6th')).toBe('5–6 место')
      expect(tx('ranked pack grind 2h')).toBe('Гринд ранкнутых паков 2 ч')
      expect(tx('farm 2.0h, 3/5 passed')).toBe('Фарм по уровню 2.0 ч, пройдено 3/5')
      expect(tx('Failed at 1:23 (45%) during a 200 BPM stream (24 notes).')).toBe('Фейл на 1:23 (45%) на стриме 200 BPM (24 нот).')
      expect(tx('Natural aim')).toBe('Талант: аим')
      expect(tx('Mioto [JP] is the new global #1!')).toBe('Mioto [JP] — новый топ-1 мира!')
      expect(tx('Some unknown chat line')).toBe('Some unknown chat line')
      expect(t('Train for {days}', { days: '5 дней' })).toBe('Тренироваться 5 дней')
    } finally {
      setLang(before, false)
    }
  })
})
