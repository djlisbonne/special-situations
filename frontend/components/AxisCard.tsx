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
  return (
    <div className="border border-rule p-4 rounded-sm">
      <div className="flex items-start justify-between gap-4 mb-2">
        <div>
          <div className="text-sm font-medium">{meta.title}</div>
          <div className="sans text-xs text-muted">{meta.blurb}</div>
        </div>
        <ScoreBar value={axis.score ?? null} />
      </div>
      {axis.rationale ? (
        <p className="text-sm mt-2 leading-snug">{axis.rationale}</p>
      ) : null}
      {axis.citations?.length ? (
        <ul className="mt-3 space-y-1">
          {axis.citations.map((c, i) => (
            <li key={i} className="sans text-xs text-muted border-l-2 border-rule pl-2 italic">
              “{c}”
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
