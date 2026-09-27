/**
 * Finds the next index in `list` (direction +1 / -1), starting after `from`,
 * whose element satisfies `accept`. With `wrap`, continues from the other end.
 * Returns -1 when nothing matches.
 */
export function findInQueue<T>(
  list: readonly T[],
  from: number,
  dir: 1 | -1,
  accept: (x: T) => boolean,
  wrap = false,
): number {
  const n = list.length;
  const steps = wrap ? n : dir === 1 ? n - 1 - from : from;
  for (let s = 1; s <= steps; s++) {
    const i = (((from + dir * s) % n) + n) % n;
    if (i === from && wrap) break;
    if (accept(list[i])) return i;
  }
  return -1;
}
