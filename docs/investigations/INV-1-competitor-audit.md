# INV-1: Competitor Audit

**Question:** What tools already exist in the LEGO build/instruction space, and what gap does Brickomancer fill?

---

## BrickIt (Brickit)

**Platform:** iOS and Android (free with optional Pro at $4.99/month; Classroom $29.99 one-time).

**What it does:** Users scatter loose bricks on a flat surface, photograph the pile, and the app uses computer vision to identify parts. It cross-references those parts against a curated database of community and official builds, shows which models are achievable, highlights each needed brick's physical location in the pile via AR overlay, and provides step-by-step building instructions within the app. Instructions are in-app only — not a downloadable PDF.

**What it does well:** AR "find this piece in your pile" highlighting is genuinely useful. The pipeline from scan to suggestion to basic instructions is end-to-end.

**Key user complaints:** Brick misidentification is common, especially for non-standard or similar-shaped parts. Color is largely ignored during scanning. No sort/filter by "number of missing pieces." Build history not retained between sessions. Suggestions skew toward small (<100 piece) builds. Instructions are simple step images, not a polished PDF.

**Parts recognition approach:** Single-photograph computer vision. Works best with 150+ bricks spread flat under good lighting. Cannot scan bags, boxes, or sorted bins.

**API / open-source:** No public API. Closed proprietary mobile app.

**Gap it leaves:** Cannot take a photo of a *target object* (a cake, a building) as the design target. No natural language input. No downloadable instruction book. No AI-generated novel designs. Instructions are pre-authored community content, not synthesized on the fly.

---

## Mecabricks

**Platform:** Web browser only (WebGL-based). Free with paid rendering tiers.

**What it does:** Premier browser-based LEGO CAD tool with high-quality geometry optimized for photorealistic rendering via an integrated Blender pipeline. Best rendering quality of any LEGO CAD tool.

**Key limitations:** Does NOT export in LDraw (.ldr/.mpd) format — models cannot be transferred to BrickLink Studio, LeoCAD, or LPub3D. No public API. No instruction-generation feature. No build-suggestion or "what can I build" capability.

**Gap it leaves:** Excellent for human-authored 3D visualization, completely inaccessible programmatically. Cannot be embedded in a pipeline.

---

## BrickLink Studio

**Platform:** Desktop (Windows and macOS). Free download.

**What it does:** Most feature-complete GUI-based LEGO CAD tool. Supports full LDraw part library, photorealistic rendering, and built-in Instruction Maker that produces step-by-step instruction pages. Exports PDF.

**Programmatic access:** No headless or CLI mode. The instruction maker and renderer require the GUI. The `.io` file format is a zip containing an LDraw file, extractable by scripts.

**Gap it leaves:** No programmatic instruction generation. Requires a human to design the model first. Cannot accept photo or text input. No build-suggestion or parts-matching feature.

---

## Rebrickable

**Platform:** Web service with REST API v3. Free tier with Pro upgrade (~$3/month).

**What it does:** Most comprehensive LEGO parts and sets database: 27,000+ official sets, 63,000+ parts, 189,000+ community MOC models. Build-suggestion feature ingests a user's part collection and calculates a "build percentage" for every set and MOC, showing what the user can build and what parts they are missing.

**Instruction generation:** Does NOT generate instructions. It hosts instruction files uploaded by MOC designers, but does not synthesize any.

**Gap it leaves:** Build suggestion only matches against the existing corpus of 189,000 MOCs/sets. Cannot generate a novel design from a photo of a target object. No image input. No instruction generation.

---

## Open-Source Projects

**Image2Lego (2021, academic)** — First published system for photo → 3D LEGO model. Uses an octree-structured autoencoder to learn a latent space from 3D voxel models, then a separate image-to-latent network. Validated by physical construction. No confirmed public GitHub repo with maintained code.

**LegoGPT / BrickGPT (2025, CMU, MIT license)** — Most significant recent work. Fine-tunes Llama-3.2-1B-Instruct on the StableText2Lego dataset (47,000+ models). Text prompt in → LDraw file + PNG render + brick-spec TXT out. Uses physics-aware rollback during autoregressive inference to guarantee stability (98.8% stability vs. 75.2% for prior approaches). Limitation: restricted to a 20×20×20 voxel grid and only 8 standard rectangular brick types. Available at `github.com/AvaLovelace1/BrickGPT` (MIT).

**Legofy** — Converts a 2D image into a mosaic that looks like 1×1 LEGO tiles. Not a 3D model generator. Useful only for 2D mosaic output.

**AJaiman/3D-to-Lego** — Converts STL files to voxel representations; brick mapping and instruction generation are listed as future work.

---

## LDraw Ecosystem

**LDraw (format/standard)** — Open standard for LEGO CAD. Plain text files describing brick placement using a library of 10,000+ part geometries. The foundation all serious open-source LEGO tools are built on.

**LeoCAD** — Open-source desktop CAD (GPL v2). Has a **CLI mode** that can render images at specific build steps. Can export CSV parts lists, HTML, OBJ, 3DS, COLLADA. Most automation-friendly LDraw viewer.

**LPub3D** — Open-source instruction-book editor (GPL v3). Accepts LDraw files and produces paginated instruction books as PDF, PNG, or JPEG. Has **batch/headless CLI mode** on all platforms. Supports multiple rendering backends (LDGlite, LDView, POV-Ray, Blender). Can generate parts lists in BrickLink XML or CSV.

**LDView** — Primarily a viewer/renderer for LDraw files. Has a CLI mode for batch rendering single steps or full models to PNG/BMP. Open source (BSD license). Used internally by LPub3D.

---

## Gaps — What None of Them Do

1. **Photo of target object → buildable LEGO model.** No shipping product accepts "here is a photo of a cake" and outputs a LEGO model design.
2. **Natural language → parts-aware novel design.** LegoGPT accepts text prompts but ignores available pieces and is limited to 8 rectangular brick types.
3. **Available-pieces-aware novel design generation.** BrickIt matches available pieces against a fixed library of pre-authored models. No tool takes available pieces as a constraint and generates a novel design.
4. **End-to-end instruction book from generated model.** The pipeline from "generated LDraw file" to "polished downloadable PDF instruction book" exists in components (LPub3D headless + LDraw) but is not assembled into any product.
5. **Multiple design suggestions with rendered previews.** No tool returns a ranked list of several LEGO interpretations of a target with images of each suggestion before committing.

---

## Recommendation: Build On vs. From Scratch

**Use these open-source components:**
- **LPub3D (GPL v3, CLI/headless mode)** for instruction book generation — given a generated LDraw file, LPub3D can produce a paginated PDF instruction book entirely from the command line.
- **LeoCAD CLI** for per-step rendering and parts list export as a lighter alternative.
- **Rebrickable API** for parts database lookup: color normalization, part ID validation, availability checks.

**Build from scratch:**
- **Vision pipeline** (photo of object → design brief): no open-source tool does this reliably.
- **Available-pieces constraint solver**: the logic that takes (set of available pieces) + (target design brief) and generates a design fitting the constraint does not exist in open source.
- **Multiple-suggestion ranking and rendered preview display**: selecting and rendering 3–5 candidate designs at different complexity tiers is novel UX not found in any existing tool.

**License note:** LPub3D is GPL v3. Calling it as a subprocess (rather than linking) is the standard approach to maintain separation for personal local use.

---

## Sources

- [Brickit App Reviews — aichief.com, brickem.io, justuseapp.com]
- [Rebrickable API Documentation](https://rebrickable.com/api/)
- [BrickLink Studio — Exporting Instructions](https://studiohelp.bricklink.com/hc/en-us/articles/5628123432215)
- [LPub3D — Official Site](https://trevorsandy.github.io/lpub3d/)
- [LeoCAD — Command Line Options](https://www.leocad.org/docs/cli.html)
- [LegoGPT / BrickGPT on GitHub](https://github.com/AvaLovelace1/BrickGPT)
- [LegoGPT paper — arXiv 2505.05469](https://arxiv.org/html/2505.05469v1)
- [Image2Lego paper — arXiv 2108.08477](https://arxiv.org/abs/2108.08477)
- [awesome-lego-machine-learning on GitHub](https://github.com/360er0/awesome-lego-machine-learning)
