/** Russian strings for integrity (reputation, accusations) and setup condition (wear, comfort, ping). */

type Out = string | ((...groups: string[]) => string)

const SETUP_CATEGORY: Record<string, string> = { mouse: 'мышь', tablet: 'планшет', keyboard: 'клавиатуру' }

export const RU_INTEGRITY: Record<string, string> = {
  'like new': 'как новое',
  used: 'б/у',
  worn: 'изношено',
  'worn out': 'убито',
  excellent: 'отлично',
  good: 'хорошо',
  'noticeable lag': 'заметные лаги',
  poor: 'плохо',
  Europe: 'Европа',
  'North America': 'Северная Америка',
  'South America': 'Южная Америка',
  Asia: 'Азия',
  Oceania: 'Океания',
  Cleared: 'Оправдан',
  Closed: 'Закрыто',
  'Restricted by mistake': 'Ошибочная блокировка',
  'A sudden climb in rank': 'Резкий взлёт в рейтинге',
  'A play far above your level': 'Плей сильно выше вашего уровня',
  'Top players always get reported': 'На топов всегда жалуются',
  'answer within {n} d': 'ответить за {n} дн.',
  'answer today': 'ответить сегодня',
  Reputation: 'Репутация',
  'Sponsors pay ×{s}, new followers ×{f}': 'Спонсоры платят ×{s}, новые подписчики ×{f}',
  'Your account is restricted until {d}: ranked scores are disabled during the review.':
    'Аккаунт ограничен до {d}: на время проверки ранкед-скоры отключены.',
  'How you look from outside': 'Как вы выглядите со стороны',
  'Past cases': 'Прошлые разбирательства',
  'no answer in time': 'ответа не было',
  'frozen for {n} d': 'заморожен на {n} дн.',
  Service: 'Обслужить',
  Replace: 'Заменить',
  'Setup condition': 'Состояние сетапа',
  'Settings comfort': 'Привычность настроек',
  'Sensitivity, tablet area and key bindings settle with consistent use and partly reset when you change gear':
    'Сенсу, область планшета и бинды помогает «притереть» ровная игра; при смене железа они частично сбиваются',
  Connection: 'Соединение',
  'lobbies ~{ms} ms': 'лобби ~{ms} мс',
  'Far-away opponents make you jumpy: +{p}% choke risk': 'Далёкие соперники нервируют: риск чоука +{p}%',
  'Your connection is no problem for online matches.': 'Соединение не мешает онлайн-матчам.',
  'Regional servers help.': 'Региональные серверы помогают.',
  'Better connection': 'Улучшить соединение',
}

export const RU_INTEGRITY_PATTERNS: [RegExp, Out][] = [
  [/^your account is restricted until (.+): ranked scores are disabled during the review$/,
    'ваш аккаунт ограничен до $1: ранкед-скоры отключены на время проверки'],
  [/^(.+) \[(\w+)\] has been restricted after a community report\.$/, '$1 [$2] ограничен после жалобы сообщества.'],
  [/^Your restriction was lifted: the review found nothing wrong\.$/, 'Ограничение снято: проверка ничего не нашла.'],
  [/^case (\d+) not found$/, 'разбирательство $1 не найдено'],
  [/^this case is already closed$/, 'это разбирательство уже закрыто'],
  [/^no such response '(.+)'$/, 'нет такого ответа «$1»'],
  [/^streaming doesn't exist yet \(Twitch launches in June 2011\)$/, 'стримов ещё нет (Twitch появится в июне 2011)'],
  [/^servicing the (\w+) costs \$(\d+); you have \$(-?\d+)$/, (c, a, b) => `обслуживание (${SETUP_CATEGORY[c] ?? c}) стоит $${a}, а у вас $${b}`],
  [/^a new (\w+) costs \$(\d+); you have \$(-?\d+)$/, (c, a, b) => `новая вещь (${SETUP_CATEGORY[c] ?? c}) стоит $${a}, а у вас $${b}`],
  [/^unknown category '(.+)'$/, 'неизвестная категория «$1»'],
  [/^no (\w+) is equipped$/, (c) => `${SETUP_CATEGORY[c] ?? c}: ничего не надето`],
  [/^your connection is already as good as it gets$/, 'соединение уже лучше некуда'],
  [/^no better plans are on offer yet$/, 'более быстрых тарифов пока нет'],
  [/^a better connection costs \$(\d+); you have \$(-?\d+)$/, 'улучшение соединения стоит $$1, а у вас $$2'],
  [/^(\d+) ms to your opponent: lag spikes make you jumpy$/, '$1 мс до соперника: лаги вас нервируют'],
]
