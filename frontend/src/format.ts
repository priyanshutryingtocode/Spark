/** A full timestamp, for a run's own header where the exact time matters. */
export function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

/** A compact day, for a list you scan.
 *
 *  The ledger's full timestamp was the loudest line in every row -- "Oct 4,
 *  2026, 8:41 PM", eighteen characters -- and it was the least important thing
 *  in it. The goal is what you scan for; the date is metadata, and the run's own
 *  header still carries the exact time, so nothing is lost by shortening it.
 *
 *  The year is kept only when it is not the current one, so a list that spans
 *  New Year still reads correctly.
 */
export function formatDay(value: string): string {
  const date = new Date(value);
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return new Intl.DateTimeFormat(
    undefined,
    sameYear
      ? { month: "short", day: "numeric" }
      : { month: "short", day: "numeric", year: "numeric" },
  ).format(date);
}
