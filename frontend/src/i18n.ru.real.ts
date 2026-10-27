/** Russian strings for plays read from the local osu! client. Merged into RU in i18n.ru.ts. */

export const RU_REAL: Record<string, string> = {
  'Played by hand': 'Сыграно руками',
  'Hand play': 'Игра руками',
  'Today by hand': 'Сегодня руками',
  'Finish the day': 'Завершить день',
  '{n} attempts, {m} of {l} minutes': 'Попыток: {n}, {m} из {l} минут',
  'Every attempt in the client costs time and energy. The longer you play, the worse your character plays. The day closes by itself at the limit.':
    'Каждая попытка в клиенте тратит время и силы. Чем дольше играете, тем хуже играет персонаж. На лимите день закроется сам.',
  'Counted in the career': 'Засчитано в карьеру',
  "this map isn't on the osu! website, the career can't know it": 'этой карты нет на сайте osu!, карьера о ней не знает',
  'nothing played by hand today': 'сегодня руками ещё ничего не сыграно',
  'Character in the client': 'Персонаж в клиенте',
  'Applied to every solo osu! map in the tycoon client. Negative means easier than the map as written.':
    'Применяется к каждой одиночной карте osu! в клиенте тайкуна. Минус — легче, чем карта на самом деле.',
  'Hit windows': 'Окна попаданий',
  'Circle size': 'Размер кругов',
  'Approach rate': 'Скорость появления',
  'HP drain': 'Потеря HP',
  'timing': 'тайминг',
  'aim': 'аим',
  'reading': 'чтение',
  'stamina': 'выносливость',
  'Cursor magnet': 'Притяжение курсора',
  'off': 'выкл',
  'condition': 'состояние',
  'Strength of stats': 'Сила влияния статов',
  'Nearby circles drift toward the cursor. Only works when aim is above average; stronger aim pulls harder.':
    'Ближние круги смещаются к курсору. Работает только при аиме выше среднего, чем сильнее аим, тем сильнее тянет.',
  'client': 'клиент',
  'failed': 'фейл',
  'quit': 'выход',
  'Sync with client': 'Синхронизировать с клиентом',
  'Syncing...': 'Синхронизация...',
  'Imported {n} earlier plays as history.': 'Загружено {n} прошлых игр как история.',
  '{n} new plays found.': 'Найдено новых игр: {n}.',
  'No new plays.': 'Новых игр нет.',
}

type Out = string | ((...groups: string[]) => string)

export const RU_REAL_PATTERNS: [RegExp, Out][] = [
  [/^not a career score: (.+) gets ranked on (\S+); it's only (\S+)$/, 'не засчитано: «$1» ранкнут только $2, а сейчас $3'],
  [/^not a career score: beatmap is (\w+): only ranked and approved maps give pp$/, 'не засчитано: карта в статусе $1, PP дают только ранкнутые'],
  [/^not a career score: (.+)$/, 'не засчитано в карьеру: $1'],
  [/^map unavailable: (.+)$/, 'карта недоступна: $1'],
  [/^match map (\w+): won ([\d,]+) to ([\d,]+)(.*)$/, 'карта матча $1: победа $2 : $3$4'],
  [/^match map (\w+): lost ([\d,]+) to ([\d,]+)(.*)$/, 'карта матча $1: поражение $2 : $3$4'],
  [/^match map not counted: play it with no mods \(NoFail allowed\)(.*)$/, 'карта матча не засчитана: играйте без модов (NoFail можно)$1'],
  [/^match map not counted: play it with (\w+) \(NoFail allowed\)(.*)$/, 'карта матча не засчитана: играйте с $1 (NoFail можно)$2'],
]
