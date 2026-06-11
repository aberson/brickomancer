import React from "react";
import type { Suggestion } from "../types";
import type { UseGenerateReturn } from "../hooks/useGenerate";

interface SuggestionsStepProps {
  hook: UseGenerateReturn;
}

const TIER_COLORS: Record<string, string> = {
  compact: "#e07b00",
  standard: "#0057a8",
  detailed: "#007a3d",
};

/** Step 3: gallery of 3 suggestion cards. */
function SuggestionsStep({ hook }: SuggestionsStepProps): React.ReactElement {
  const { suggestions, loading, error, generateInstructions } = hook;

  return (
    <div>
      <h2 style={{ marginBottom: "1rem" }}>Build suggestions</h2>
      {error && <p style={{ color: "red", marginBottom: "0.8rem" }}>{error}</p>}
      <div
        style={{
          display: "flex",
          gap: "1.25rem",
          flexWrap: "wrap",
        }}
      >
        {suggestions.map((s: Suggestion) => (
          <SuggestionCard
            key={s.id}
            suggestion={s}
            loading={loading}
            onGenerate={generateInstructions}
          />
        ))}
      </div>
    </div>
  );
}

interface CardProps {
  suggestion: Suggestion;
  loading: boolean;
  onGenerate: (id: string) => Promise<void>;
}

function SuggestionCard({
  suggestion,
  loading,
  onGenerate,
}: CardProps): React.ReactElement {
  const tierColor = TIER_COLORS[suggestion.tier] ?? "#666";

  return (
    <div
      style={{
        border: "1px solid #ddd",
        borderRadius: 8,
        padding: "1rem",
        width: 220,
        display: "flex",
        flexDirection: "column",
        gap: "0.6rem",
        boxShadow: "0 2px 6px rgba(0,0,0,0.08)",
      }}
    >
      {/* Preview image */}
      {suggestion.preview_url ? (
        <img
          src={suggestion.preview_url}
          alt={`${suggestion.tier} preview`}
          style={{ width: "100%", height: 160, objectFit: "contain", background: "#f8f8f8" }}
        />
      ) : (
        <div
          style={{
            width: "100%",
            height: 160,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "#f0f0f0",
            color: "#999",
            fontSize: "0.85rem",
            borderRadius: 4,
          }}
        >
          No preview available
        </div>
      )}

      {/* Tier badge */}
      <span
        style={{
          display: "inline-block",
          background: tierColor,
          color: "#fff",
          padding: "0.2rem 0.6rem",
          borderRadius: 4,
          fontSize: "0.8rem",
          fontWeight: "bold",
          textTransform: "capitalize",
          alignSelf: "flex-start",
        }}
      >
        {suggestion.tier}
      </span>

      {/* Parts count */}
      <p style={{ margin: 0, fontSize: "0.9rem", color: "#444" }}>
        {suggestion.parts_count} part{suggestion.parts_count !== 1 ? "s" : ""}
      </p>

      {/* Generate button */}
      <button
        type="button"
        disabled={loading}
        onClick={() => void onGenerate(suggestion.id)}
        style={{
          marginTop: "auto",
          padding: "0.5rem 0.8rem",
          background: "#0057a8",
          color: "#fff",
          border: "none",
          borderRadius: 4,
          cursor: "pointer",
          opacity: loading ? 0.5 : 1,
        }}
      >
        {loading ? "Generating..." : "Generate Instructions"}
      </button>
    </div>
  );
}

export default SuggestionsStep;
