// Bound input length below MiniLM's 256-token limit for typical prose.
export function chunks(text, size = 600, overlap = 80) {
  text = text.replace(/\r\n/g, "\n").trim();
  const result = [];
  for (let start = 0; start < text.length; start += size - overlap) {
    result.push(text.slice(start, start + size));
    if (start + size >= text.length) break;
  }
  return result;
}

export function recallAtK(ids, relevant, k = 3) {
  return (
    relevant.filter((id) => ids.slice(0, k).includes(id)).length /
    relevant.length
  );
}
export function ndcgAtK(ids, relevant, k = 3) {
  const dcg = ids
    .slice(0, k)
    .reduce(
      (sum, id, i) => sum + (relevant.includes(id) ? 1 / Math.log2(i + 2) : 0),
      0,
    );
  const ideal = relevant
    .slice(0, k)
    .reduce((sum, _, i) => sum + 1 / Math.log2(i + 2), 0);
  return ideal ? dcg / ideal : 0;
}
export const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  const i = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[i] : (sorted[i - 1] + sorted[i]) / 2;
};
