/** Russian strings for the search feature. Merged into RU / RU_PATTERNS in i18n.ru.ts. */

type Out = string | ((...groups: string[]) => string)

export const RU_SEARCH: Record<string, string> = {
  'Compare': 'Сравнить',
  'restricted': 'заблокирован',
  'player': 'игрок',
  'real player': 'реальный игрок',
  'Peak rank': 'Пиковый ранг',
  'Head to head': 'Личные встречи',
  'Player': 'Игрок',
  'also known as': 'также известен как',
  'Message': 'Написать',
  'Your rival': 'Ваш соперник',
  'heat {n}': 'накал {n}',
  'Teammate': 'Тиммейт',
  'Your mentor': 'Ваш наставник',
  'Overall': 'Общий уровень',
  'Skills': 'Навыки',
  'Strong at': 'Сильные стороны',
  'Weak at': 'Слабые стороны',
  'Recent activity': 'Последние события',
  'Nothing notable lately.': 'В последнее время ничего примечательного.',
  'No scores on the boards you have seen yet.': 'На открытых вами досках его скоров пока нет.',
  'Search maps and players (Ctrl+K)': 'Поиск карт и игроков (Ctrl+K)',
  'Search maps and players…': 'Поиск карт и игроков…',
  'Nothing found.': 'Ничего не найдено.',
  'Type a map, artist, mapper or player name. ↑↓ to move, Enter to open.': 'Введите карту, исполнителя, маппера или ник. ↑↓ — выбор, Enter — открыть.',
  'Players': 'Игроки',
  'Maps': 'Карты',
  'Full profile': 'Полный профиль',
  'Search': 'Поиск',
}

export const RU_SEARCH_PATTERNS: [RegExp, Out][] = []
