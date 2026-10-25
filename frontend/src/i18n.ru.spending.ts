/** Russian strings for the spending feature. Merged into RU / RU_PATTERNS in i18n.ru.ts. */

type Out = string | ((...groups: string[]) => string)

export const RU_SPENDING: Record<string, string> = {
  'Services & perks': 'Услуги и бонусы',
  Subscriptions: 'Подписки',
  'one-off': 'разово',
  temporary: 'на время',
  monthly: 'ежемесячно',
  'yours for good': 'навсегда',
  'Not enough money': 'Не хватает денег',
  Owned: 'Куплено',
  Subscribed: 'Оформлено',
  Active: 'Действует',
  'In {n} d': 'Через {n} дн.',
  Locked: 'Недоступно',
  Subscribe: 'Оформить',
  Buy: 'Купить',
  mo: 'мес',
  '{n} mo': '{n} мес',
  'Skill group': 'Группа навыков',
  'Your money': 'Ваши деньги',
  'Subscriptions per month': 'Подписки в месяц',
}

export const RU_SPENDING_PATTERNS: [RegExp, Out][] = [
  [/^no such item '(.+)'$/, 'нет такого товара: $1'],
  [/^choose a skill group: (.+)$/, 'выберите группу навыков'],
  [/^you are not subscribed to that$/, 'вы не подписаны на это'],
  [/^Not available before (\d+)$/, 'Недоступно до $1 года'],
  [/^From age (.+)$/, 'С $1 лет'],
  [/^Needs (\d+) followers$/, 'Нужно $1 подписчиков'],
  [/^Needs a rank of #(.+) or better$/, 'Нужен ранг #$1 или выше'],
  [/^Needs a team with two active teammates$/, 'Нужна команда минимум с двумя активными товарищами'],
  [/^Needs a registered Open, Major or World Cup within 45 days$/, 'Нужен турнир уровня Open, Major или World Cup в ближайшие 45 дней, куда вы записаны'],
  [/^For tablet players$/, 'Для игроков на планшете'],
  [/^For mouse players$/, 'Для игроков на мыши'],
  [/^Streaming doesn't exist yet$/, 'Стримов ещё не существует'],
  [/^Its effect is still running$/, 'Эффект ещё действует'],
  [/^Again in (\d+) d$/, 'Снова через $1 дн.'],
  [/^Your connection is as good as it gets$/, 'Соединение уже лучше некуда'],
  [/^Couldn't pay for (.+): the subscription was cancelled\.$/, 'Не удалось оплатить «$1»: подписка отменена.'],
  [/^Bought: (.+) \(\$(\d+)\)\.(.*)$/, 'Куплено: $1 ($$2).'],
  [/^Cancelled: (.+)\.$/, 'Отменено: $1.'],
]
