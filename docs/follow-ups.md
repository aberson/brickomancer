# Brickomancer follow-ups

Post-rebuild work register, established 2026-09-02 during the repo cleanup that closed eight
issues orphaned by superseded plans (#4, #13, #16, #22, #23, #32, #34, #35). Nothing here blocks
the rebuild, which is COMPLETE; this file exists so closing those issues did not drop real work.

The rebuild itself is recorded in [`documentation/rebuild-plan.md`](../documentation/rebuild-plan.md)
(the plan of record). The calibration analysis behind most of the harness items is
[`docs/investigations/rebuild/05-calibration-result.md`](investigations/rebuild/05-calibration-result.md).

## Tracked (has a GitHub issue)

| # | Item | Why it matters |
|---|---|---|
| [#60](https://github.com/aberson/brickomancer/issues/60) | Harness developer step round-trips whole files through JSON | The single reason the calibration loop cannot hill-climb. 2 of 3 Step 10 iterations died here (`SKIPPED_DEV`). Highest leverage item in this file. |
| [#61](https://github.com/aberson/brickomancer/issues/61) | `SKIPPED_JUDGE` conflates a parse failure with non-empty `blocking_issues` | The third Step 10 failure, and the tag ambiguity already sent one fix at the wrong target. |
| [#62](https://github.com/aberson/brickomancer/issues/62) | `/run-harness` skill still drives the deleted v1 layout | It is the operator entry point for the harness and is broken end to end. |
| [#63](https://github.com/aberson/brickomancer/issues/63) | Manual browser UAT of the rebuilt wizard | No browser pass has ever been recorded on the rebuilt stack. Also owns the `llama_server_ok` contract reference orphaned by closing #13. |
| [#64](https://github.com/aberson/brickomancer/issues/64) | Piece detection is a no-op as a build constraint | User-visible feature that is plumbed end to end and then ignored. Silent-wiring failure. |
| [#65](https://github.com/aberson/brickomancer/issues/65) | LDView `-ExportFile=1` pollutes the repo root | Recurring junk artifact; deleting it alone has already failed once. `.gitignore` currently carries `/1` as cover, not a fix. |

## Untracked backlog (no issue yet - open one when picked up)

- **Step 5 live star-survival check.** Step 5's literal done-when (top-down silhouette shows >= 4
  star protrusions) was explicitly deferred to an operator test and never run. The script exists at
  `scripts/step5_star_survival_uat.py`; it needs a CUDA GPU.
- **`build_stability` = 3.0 is real packer headroom.** The only non-maxed scorer dimension, and it
  is genuinely failing: the scorer awards 10.0 only for 1 connected component AND 0 unsupported
  bricks, and the text-shaped eval builds (star / dog / chair / heart) score 3.0. The packer holds
  the contract on its own cube/star fixtures, but text-emitted grids still expose fragility. This is
  also the surviving half of #32's success criteria (`build_stability 1 -> >= 5`, still measurable,
  still unmet). Attacking it needs #60 first.
- **Richer scorer dimensions.** 3 of 4 dimensions are already maxed at 10.0, so even a working
  developer step would have little to climb. Adding the LLM-judged rendered dimensions
  (`shape_fidelity`, `aesthetics`, `instruction_clarity`) restores headroom - and `shape_fidelity`
  is exactly the dimension whose loss made half of #32's criteria unevaluable.
- **rembg's default model has never been compared against the Hunyuan3D front end.** #35 proposed
  u2net -> birefnet-general for v1 and never ran; `src/brickomancer/services/image_shaper.py:180-183`
  still calls `remove()` with no `session=`. Lower stakes than in v1 (the mask now feeds a 3D
  generator rather than setting the shape directly), but simply unmeasured.
- **Minimum-depth slab height fallback.** Z=2 slabs, and Y=2 with Z in {5,9}, still gain +1/+2
  layers via the cap fallback. They stay 1 component / 0 unsupported, and every thick grid
  (Y>=3 and Z>=3) is zero-added-height, so this is a known limit rather than a defect.
- **Image-path warm-request timing has not been re-measured.** The ~17 min figure predates the
  process-wide pipeline cache (`f471412`). Later requests in a process are projected toward ~100 s;
  nobody has measured it.
- **Dead v1 types and doc drift.** Residue from the goblin scan: v1 types that no longer have a
  consumer, and test counts quoted in docs that no longer match the 285-passing / 288-collected
  reality.
