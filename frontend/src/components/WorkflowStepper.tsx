import React from "react";
import { useGenerate } from "../hooks/useGenerate";
import InputStep from "./InputStep";
import PiecesStep from "./PiecesStep";
import SuggestionsStep from "./SuggestionsStep";
import InstructionsStep from "./InstructionsStep";

const STEP_LABELS = ["Input", "Pieces", "Suggestions", "Instructions"];

/** Top-level step manager — renders the active step based on useGenerate. */
function WorkflowStepper(): React.ReactElement {
  const hook = useGenerate();
  const { step } = hook;

  return (
    <div style={{ fontFamily: "sans-serif", padding: "2rem" }}>
      <h1 style={{ marginBottom: "1.5rem" }}>Brickomancer</h1>

      {/* Step indicator */}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "2rem" }}>
        {STEP_LABELS.map((label, idx) => {
          const active = idx === step;
          const done = idx < step;
          return (
            <div
              key={label}
              style={{ display: "flex", alignItems: "center", gap: "0.35rem" }}
            >
              <div
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: "50%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: active
                    ? "#0057a8"
                    : done
                    ? "#007a3d"
                    : "#ddd",
                  color: active || done ? "#fff" : "#666",
                  fontWeight: "bold",
                  fontSize: "0.85rem",
                }}
              >
                {done ? "✓" : idx + 1}
              </div>
              <span
                style={{
                  fontSize: "0.85rem",
                  color: active ? "#0057a8" : done ? "#007a3d" : "#999",
                  fontWeight: active ? "bold" : "normal",
                }}
              >
                {label}
              </span>
              {idx < STEP_LABELS.length - 1 && (
                <span style={{ color: "#ccc", margin: "0 0.25rem" }}>›</span>
              )}
            </div>
          );
        })}
      </div>

      {/* Active step */}
      {step === 0 && <InputStep hook={hook} />}
      {step === 1 && <PiecesStep hook={hook} />}
      {step === 2 && <SuggestionsStep hook={hook} />}
      {step === 3 && <InstructionsStep hook={hook} />}
    </div>
  );
}

export default WorkflowStepper;
