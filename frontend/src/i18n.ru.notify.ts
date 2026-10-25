/** Russian strings for the notify feature. Merged into RU / RU_PATTERNS in i18n.ru.ts. */

type Out = string | ((...groups: string[]) => string)

export const RU_NOTIFY: Record<string, string> = {
  'New message from {name}': 'Новое сообщение от {name}',
  Register: 'Записаться',
  Notifications: 'Уведомления',
  'Mark all as read': 'Прочитать все',
  'Nothing new.': 'Ничего нового.',
  'Shortcut: {key}': 'Клавиша: {key}',
  'Rest 1 day': 'Отдых 1 день',
  'Live a week': 'Прожить неделю',
  'Auto session': 'Авто-сессия',
  'Keyboard shortcuts': 'Горячие клавиши',
  'Rest one day': 'Отдохнуть один день',
  'Switch group': 'Переключить группу вкладок',
  'Training / Play / Tournaments / World / Chats / Forum': 'Тренировки / Игра / Турниры / Мир / Чаты / Форум',
  'Profile / Story / Team / Life / Legacy': 'Профиль / Сюжет / Команда / Жизнь / Наследие',
  Search: 'Поиск',
  'This help': 'Эта подсказка',
  'Shortcuts are ignored while you type.': 'Пока вы печатаете, горячие клавиши не срабатывают.',
  'Play the same maps with the same mods and attempts': 'Сыграть те же карты с теми же модами и числом попыток',
  'Play again': 'Сыграть снова',
  'A new session from the same preset and hours': 'Новая сессия по тому же пресету и часам',
  'Same preset': 'Тот же пресет',
  'Same preset ({h}h)': 'Тот же пресет ({h} ч)',
}

export const RU_NOTIFY_PATTERNS: [RegExp, Out][] = []
