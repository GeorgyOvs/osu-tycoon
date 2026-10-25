/** Links to the real osu! website are switched off for now; flip this to bring them back everywhere. */
export const SHOW_EXTERNAL_LINKS = false

export function beatmapUrl(beatmapId: number): string | null {
  return SHOW_EXTERNAL_LINKS ? `https://osu.ppy.sh/b/${beatmapId}` : null
}
