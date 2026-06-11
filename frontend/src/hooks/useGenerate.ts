/** useGenerate hook — fetch wrapper for POST /api/generate/* */

import { useState } from "react";
import type { GenerateResponse, Suggestion } from "../types";

export interface UseGenerateReturn {
  step: number;
  loading: boolean;
  suggestions: Suggestion[];
  instructionsPdfUrl: string | null;
  error: string | null;
  submitImage: (
    file: File,
    pieceImages: File[],
    heightStuds: number
  ) => Promise<void>;
  submitText: (
    description: string,
    pieceImages: File[],
    heightStuds: number
  ) => Promise<void>;
  submitPieces: (files: File[]) => void;
  generateInstructions: (suggestionId: string) => Promise<void>;
  reset: () => void;
  // Internal state for the pieces step
  _pendingInput: PendingInput | null;
}

type PendingInput =
  | { kind: "image"; file: File; heightStuds: number }
  | { kind: "text"; description: string; heightStuds: number };

export function useGenerate(): UseGenerateReturn {
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [instructionsPdfUrl, setInstructionsPdfUrl] = useState<string | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);
  const [_pendingInput, setPendingInput] = useState<PendingInput | null>(null);

  /** Step 0 → 1: save input, advance to pieces step. */
  async function submitImage(
    file: File,
    _pieceImages: File[],
    heightStuds: number
  ): Promise<void> {
    setPendingInput({ kind: "image", file, heightStuds });
    setError(null);
    setStep(1);
  }

  async function submitText(
    description: string,
    _pieceImages: File[],
    heightStuds: number
  ): Promise<void> {
    setPendingInput({ kind: "text", description, heightStuds });
    setError(null);
    setStep(1);
  }

  /** Step 1 → 2: fire the generation API with accumulated piece files. */
  function submitPieces(files: File[]): void {
    if (_pendingInput === null) {
      setError("No pending input — go back to step 1.");
      return;
    }
    const pending = _pendingInput;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        let data: GenerateResponse;
        if (pending.kind === "image") {
          data = await _postFromImage(pending.file, files, pending.heightStuds);
        } else {
          data = await _postFromText(
            pending.description,
            files,
            pending.heightStuds
          );
        }
        setSuggestions(data.suggestions);
        setStep(2);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    })();
  }

  /** Step 2 → 3: generate PDF for selected suggestion. */
  async function generateInstructions(suggestionId: string): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/generate/instructions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ suggestion_id: suggestionId }),
      });
      if (!response.ok) {
        const detail = await response
          .json()
          .then((j: { detail?: string }) => j.detail ?? response.statusText)
          .catch(() => response.statusText);
        throw new Error(`Instructions failed: ${detail}`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      setInstructionsPdfUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return url;
      });
      setStep(3);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  function reset(): void {
    if (instructionsPdfUrl) URL.revokeObjectURL(instructionsPdfUrl);
    setStep(0);
    setLoading(false);
    setSuggestions([]);
    setInstructionsPdfUrl(null);
    setError(null);
    setPendingInput(null);
  }

  return {
    step,
    loading,
    suggestions,
    instructionsPdfUrl,
    error,
    submitImage,
    submitText,
    submitPieces,
    generateInstructions,
    reset,
    _pendingInput,
  };
}

// ---------------------------------------------------------------------------
// Private fetch helpers
// ---------------------------------------------------------------------------

async function _postFromImage(
  image: File,
  pieceImages: File[],
  heightStuds: number
): Promise<GenerateResponse> {
  const fd = new FormData();
  fd.append("image", image);
  fd.append("height_studs", String(heightStuds));
  for (const f of pieceImages) {
    fd.append("piece_images", f);
  }
  const res = await fetch("/api/generate/from-image", {
    method: "POST",
    body: fd,
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((j: { detail?: string }) => j.detail ?? res.statusText)
      .catch(() => res.statusText);
    throw new Error(`Generate from image failed: ${detail}`);
  }
  return res.json() as Promise<GenerateResponse>;
}

async function _postFromText(
  description: string,
  _pieceImages: File[],
  heightStuds: number
): Promise<GenerateResponse> {
  const res = await fetch("/api/generate/from-text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ description, height_studs: heightStuds }),
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((j: { detail?: string }) => j.detail ?? res.statusText)
      .catch(() => res.statusText);
    throw new Error(`Generate from text failed: ${detail}`);
  }
  return res.json() as Promise<GenerateResponse>;
}
