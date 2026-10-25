/** Open an NPC profile or a DM from anywhere without threading callbacks through every panel. */

export type OpenNpc = { id?: number; name?: string; compare?: boolean }

export const OPEN_NPC = 'tycoon:open-npc'
export const OPEN_DM = 'tycoon:open-dm'

export function openNpc(detail: OpenNpc) {
  window.dispatchEvent(new CustomEvent<OpenNpc>(OPEN_NPC, { detail }))
}

export function openDm(name: string) {
  window.dispatchEvent(new CustomEvent<string>(OPEN_DM, { detail: name }))
}
