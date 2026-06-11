import React, { useState, useRef } from "react";
import type { UseGenerateReturn } from "../hooks/useGenerate";

interface InputStepProps {
  hook: UseGenerateReturn;
}

/** Step 1: image upload or text description with toggle. */
function InputStep({ hook }: InputStepProps): React.ReactElement {
  const [mode, setMode] = useState<"image" | "text">("image");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [heightStuds, setHeightStuds] = useState(10);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { loading, error } = hook;

  function handleSubmit(e: React.FormEvent): void {
    e.preventDefault();
    if (mode === "image") {
      if (!imageFile) return;
      void hook.submitImage(imageFile, [], heightStuds);
    } else {
      if (!description.trim()) return;
      void hook.submitText(description.trim(), [], heightStuds);
    }
  }

  return (
    <div style={{ maxWidth: 480 }}>
      <h2 style={{ marginBottom: "1rem" }}>Describe your build</h2>

      {/* Toggle */}
      <div style={{ marginBottom: "1rem", display: "flex", gap: "0.5rem" }}>
        <button
          type="button"
          onClick={() => setMode("image")}
          style={{
            padding: "0.4rem 1rem",
            fontWeight: mode === "image" ? "bold" : "normal",
            background: mode === "image" ? "#0057a8" : "#eee",
            color: mode === "image" ? "#fff" : "#333",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
          }}
        >
          Upload image
        </button>
        <button
          type="button"
          onClick={() => setMode("text")}
          style={{
            padding: "0.4rem 1rem",
            fontWeight: mode === "text" ? "bold" : "normal",
            background: mode === "text" ? "#0057a8" : "#eee",
            color: mode === "text" ? "#fff" : "#333",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
          }}
        >
          Describe in text
        </button>
      </div>

      <form onSubmit={handleSubmit}>
        {mode === "image" ? (
          <div style={{ marginBottom: "1rem" }}>
            <label style={{ display: "block", marginBottom: "0.4rem" }}>
              Photo of object
            </label>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              onChange={(e) =>
                setImageFile(e.target.files ? e.target.files[0] ?? null : null)
              }
              style={{ display: "block" }}
            />
            {imageFile && (
              <p style={{ fontSize: "0.85rem", color: "#555", marginTop: "0.4rem" }}>
                Selected: {imageFile.name}
              </p>
            )}
          </div>
        ) : (
          <div style={{ marginBottom: "1rem" }}>
            <label
              htmlFor="description"
              style={{ display: "block", marginBottom: "0.4rem" }}
            >
              Description
            </label>
            <textarea
              id="description"
              rows={4}
              style={{ width: "100%", padding: "0.5rem", boxSizing: "border-box" }}
              placeholder="e.g. a red fire truck, a round blue tower..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        )}

        <div style={{ marginBottom: "1rem" }}>
          <label
            htmlFor="height-studs"
            style={{ display: "block", marginBottom: "0.4rem" }}
          >
            Target height (studs)
          </label>
          <input
            id="height-studs"
            type="number"
            min={1}
            max={100}
            value={heightStuds}
            onChange={(e) => setHeightStuds(Number(e.target.value))}
            style={{ width: 80, padding: "0.4rem" }}
          />
        </div>

        {error && (
          <p style={{ color: "red", marginBottom: "0.8rem" }}>{error}</p>
        )}

        <button
          type="submit"
          disabled={
            loading ||
            (mode === "image" ? !imageFile : !description.trim())
          }
          style={{
            padding: "0.6rem 1.4rem",
            background: "#0057a8",
            color: "#fff",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
            opacity:
              loading || (mode === "image" ? !imageFile : !description.trim())
                ? 0.5
                : 1,
          }}
        >
          {loading ? "Loading..." : "Next"}
        </button>
      </form>
    </div>
  );
}

export default InputStep;
