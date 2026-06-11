import React, { useState } from "react";
import type { UseGenerateReturn } from "../hooks/useGenerate";

interface PiecesStepProps {
  hook: UseGenerateReturn;
}

/** Step 2: optional multi-photo upload of LEGO piece inventory. */
function PiecesStep({ hook }: PiecesStepProps): React.ReactElement {
  const [files, setFiles] = useState<File[]>([]);
  const { loading, error } = hook;

  function handleFiles(e: React.ChangeEvent<HTMLInputElement>): void {
    if (!e.target.files) return;
    setFiles(Array.from(e.target.files));
  }

  function handleNext(): void {
    hook.submitPieces(files);
  }

  function handleSkip(): void {
    hook.submitPieces([]);
  }

  return (
    <div style={{ maxWidth: 480 }}>
      <h2 style={{ marginBottom: "0.5rem" }}>Your LEGO pieces (optional)</h2>
      <p style={{ color: "#555", marginBottom: "1rem" }}>
        Upload photos of your available LEGO pieces so the generator can
        suggest a build that uses what you already own. Skip to generate
        without this constraint.
      </p>

      <div style={{ marginBottom: "1rem" }}>
        <label style={{ display: "block", marginBottom: "0.4rem" }}>
          Piece photos
        </label>
        <input
          type="file"
          accept="image/*"
          multiple
          onChange={handleFiles}
          style={{ display: "block" }}
        />
        {files.length > 0 && (
          <p style={{ fontSize: "0.85rem", color: "#555", marginTop: "0.4rem" }}>
            {files.length} file{files.length !== 1 ? "s" : ""} selected:{" "}
            {files.map((f) => f.name).join(", ")}
          </p>
        )}
      </div>

      {error && (
        <p style={{ color: "red", marginBottom: "0.8rem" }}>{error}</p>
      )}

      <div style={{ display: "flex", gap: "0.75rem" }}>
        <button
          type="button"
          onClick={handleSkip}
          disabled={loading}
          style={{
            padding: "0.6rem 1.2rem",
            background: "#eee",
            color: "#333",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
            opacity: loading ? 0.5 : 1,
          }}
        >
          {loading ? "Generating..." : "Skip"}
        </button>
        <button
          type="button"
          onClick={handleNext}
          disabled={loading || files.length === 0}
          style={{
            padding: "0.6rem 1.4rem",
            background: "#0057a8",
            color: "#fff",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
            opacity: loading || files.length === 0 ? 0.5 : 1,
          }}
        >
          {loading ? "Generating..." : "Next"}
        </button>
      </div>
    </div>
  );
}

export default PiecesStep;
