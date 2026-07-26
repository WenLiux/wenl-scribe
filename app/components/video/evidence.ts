type TimedSegment = {
  start: number | null;
  end: number | null;
  text: string;
};

function compact(value: string) {
  return value.replace(/\s+/g, "");
}

export function locateEvidenceTimestamp(
  evidence: string,
  segments: TimedSegment[] | null | undefined,
  fallback: number | null | undefined,
) {
  const needle = compact(evidence || "");
  if (needle.length < 2 || !segments?.length) return fallback ?? null;

  const compactSegments = segments.map(segment => compact(segment.text || ""));
  const transcript = compactSegments.join("");
  const evidenceOffset = transcript.indexOf(needle);
  if (evidenceOffset < 0) return fallback ?? null;

  let cursor = 0;
  for (let index = 0; index < segments.length; index += 1) {
    const textLength = compactSegments[index].length;
    const segmentEnd = cursor + textLength;
    if (evidenceOffset < segmentEnd || (textLength === 0 && evidenceOffset === cursor)) {
      const segment = segments[index];
      if (segment.start == null) return fallback ?? null;
      if (segment.end == null || segment.end <= segment.start || textLength === 0) return segment.start;
      const progress = Math.max(0, Math.min(1, (evidenceOffset - cursor) / textLength));
      return Math.round((segment.start + (segment.end - segment.start) * progress) * 10) / 10;
    }
    cursor = segmentEnd;
  }
  return fallback ?? null;
}
