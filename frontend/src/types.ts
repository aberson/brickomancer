/** TypeScript types matching the Pydantic schemas in src/brickomancer/models/schemas.py */

export type SuggestionTier = "compact" | "standard" | "detailed";

export interface PartCount {
  part_id: string;
  color_name: string;
  color_hex: string;
  qty: number;
}

export interface Suggestion {
  id: string;
  tier: SuggestionTier;
  preview_url: string;
  parts_count: number;
  parts_list: PartCount[];
}

export interface GenerateResponse {
  suggestions: Suggestion[];
}
