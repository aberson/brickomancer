import React from "react";
import type { UseGenerateReturn } from "../hooks/useGenerate";

interface InstructionsStepProps {
  hook: UseGenerateReturn;
}

/** Step 4: spinner during PDF generation, download link on success. */
function InstructionsStep({ hook }: InstructionsStepProps): React.ReactElement {
  const { loading, instructionsPdfUrl, error, reset } = hook;

  return (
    <div style={{ maxWidth: 480 }}>
      <h2 style={{ marginBottom: "1rem" }}>Instruction book</h2>

      {loading && (
        <div style={{ marginBottom: "1rem" }}>
          <p style={{ color: "#555" }}>Generating PDF — this may take a moment...</p>
          <div
            style={{
              width: 40,
              height: 40,
              border: "4px solid #ddd",
              borderTop: "4px solid #0057a8",
              borderRadius: "50%",
              animation: "spin 0.8s linear infinite",
            }}
          />
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {error && !loading && (
        <p style={{ color: "red", marginBottom: "0.8rem" }}>{error}</p>
      )}

      {instructionsPdfUrl && !loading && (
        <div style={{ marginBottom: "1rem" }}>
          <p style={{ color: "#007a3d", marginBottom: "0.8rem" }}>
            Your instruction book is ready!
          </p>
          <a
            href={instructionsPdfUrl}
            download="brickomancer-instructions.pdf"
            style={{
              display: "inline-block",
              padding: "0.6rem 1.4rem",
              background: "#007a3d",
              color: "#fff",
              textDecoration: "none",
              borderRadius: 4,
            }}
          >
            Download PDF
          </a>
        </div>
      )}

      <button
        type="button"
        onClick={reset}
        style={{
          padding: "0.6rem 1.2rem",
          background: "#eee",
          color: "#333",
          border: "none",
          borderRadius: 4,
          cursor: "pointer",
          marginTop: instructionsPdfUrl || error ? "1rem" : 0,
        }}
      >
        Start Over
      </button>
    </div>
  );
}

export default InstructionsStep;
