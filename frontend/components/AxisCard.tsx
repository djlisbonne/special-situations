import { AxisScore } from "@/lib/api";
import { ScoreBar } from "./ScoreBar";

const AXIS_LABELS: Record<string, { title: string; blurb: string }> = {
  insider_alignment: {
    title: "Insider alignment",
    blurb: "Does post-spin management have meaningful skin in the game?",
  },
  forced_selling: {
    title: "Forced selling",
    blurb: "Will mechanical, price-insensitive sellers hit the tape?",
  },
  hidden_value: {
    title: "Hidden value",
    blurb: "Does the rationale point to unlocked value, not defensive moves?",
  },
  leverage_profile: {
    title: "Leverage profile",
    blurb: "Is the capital structure asymmetric in the investor's favor?",
  },
  information_asymmetry: {
    title: "Information asymmetry",
    blurb: "Under-covered enough for an informed retail investor to have edge?",
  },
};

export function AxisCard({ name, axis }: { name: string; axis: AxisScore }) {
  const meta = AXIS_LABELS[name] ?? { title: name, blurb: "" };
  const positive = axis.positive_evidence?.length
    ? axis.positive_evidence
    : axis.citations ?? [];
  const negative = axis.negative_evidence ?? [];
  return (
    <div className="border border-rule p-4 rounded-sm">
      <div className="flex items-start justify-between gap-4 mb-2">
        <div>
          <div className="text-sm font-medium">{meta.title}</div>
          <div className="sans text-xs text-muted">{meta.blurb}</div>
          {typeof axis.confidence === "number" && (
            <div className="sans text-xs text-muted mt-1">
              Confidence {(axis.confidence * 100).toFixed(0)}%
            </div>
          )}
        </div>
        <ScoreBar value={axis.score ?? null} />
      </div>
      {axis.rationale ? (
        <p className="text-sm mt-2 leading-snug">{axis.rationale}</p>
      ) : null}
      {positive.length ? (
        <ul className="mt-3 space-y-1">
          {positive.map((c, i) => (
            <li key={i} className="sans text-xs text-muted border-l-2 border-rule pl-2 italic">
              “{c}”
            </li>
          ))}
        </ul>
      ) : null}
      {negative.length ? (
        <div className="mt-3">
          <div className="sans text-xs uppercase tracking-wide text-muted mb-1">
            Negative evidence
          </div>
          <ul className="space-y-1">
            {negative.map((c, i) => (
              <li key={i} className="sans text-xs text-muted border-l-2 border-rule pl-2">
                {c}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
