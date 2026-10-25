/** Russian strings for the interactive ban/pick draft. Merged into RU / RU_PATTERNS in i18n.ru.ts. */

type Out = string | ((...groups: string[]) => string)

export const RU_DRAFT: Record<string, string> = {
  'Draft room': 'Драфт-комната',
  'Open the draft room': 'Войти в драфт-комнату',
  'Auto (AI plays my side)': 'Авто (ИИ играет за меня)',
  'Your turn: ban a map': 'Ваш ход: забаньте карту',
  'Your turn: pick a map': 'Ваш ход: выберите карту',
  'Waiting for {name}…': 'Ждём ход {name}…',
  'The match is over': 'Матч окончен',
  'You win {a}–{b}': 'Вы победили {a}–{b}',
  'You lose {a}–{b}': 'Вы проиграли {a}–{b}',
  'Continue': 'Продолжить',
  'Warm up (30 min)': 'Размяться (30 мин)',
  'Warmed up: a bit more form and nerve for this match': 'Разминка сделана: чуть больше формы и стойкости на этот матч',
  'Warm-up costs a little stamina': 'Разминка немного утомляет',
  'Auto-finish': 'Доиграть автоматически',
  'seed {n}': 'посев {n}',
  'First to {n}': 'До {n} побед',
  'Bans are made first by the better seed, picks start with the other side. Each pick is played at once.':
    'Первым банит игрок с лучшим посевом, а пики начинает другая сторона. Каждая выбранная карта играется сразу.',
  'Order of events': 'Ход драфта',
  'Results': 'Результаты',
  'banned': 'забанил',
  'picked': 'выбрал',
  'tiebreaker': 'тайбрейкер',
  'banned by {name}': 'забанил {name}',
  'picked by {name}': 'выбрал {name}',
  'Played': 'Сыграна',
  'You': 'Вы',
  'Tie': 'Ничья',
  'Nothing has been decided yet.': 'Пока ничего не решено.',
  'open': 'свободна',
  'bans': 'баны',
}

export const RU_DRAFT_PATTERNS: [RegExp, Out][] = [
  [/^it is not your turn$/, 'сейчас не ваш ход'],
  [/^open the draft first$/, 'сначала откройте драфт'],
  [/^this draft is already finished$/, 'драфт уже завершён'],
  [/^you have already warmed up for this match$/, 'вы уже разминались перед этим матчем'],
  [/^the warm-up is before the first map$/, 'разминка возможна только до первой карты'],
  [/^the match is over$/, 'матч уже окончен'],
  [/^(\w+) is not available$/, '$1 недоступна'],
  [/^this match has already been played$/, 'этот матч уже сыгран'],
  [/^no draft for this match$/, 'для этого матча нет драфта'],
]
