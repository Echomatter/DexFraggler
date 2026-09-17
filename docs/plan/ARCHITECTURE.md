# DexFraggler Research Architecture

## End-to-end

```text
                     LEGAL DX7 PATCH SPACE
                              │
              ┌───────────────┴────────────────┐
              │                                │
      structural descriptors            native renderer
      exact legal constraints            Dexed Mark I
      analytic move helpers                    │
              │                                ▼
              │                         NativeObservation
              │                                │
              │                    ┌───────────┴───────────┐
              │                    │                       │
              │                    ▼                       ▼
              │             forward model            training corpus
              │             patch → wave                  │
              │                    │                       │
              └────────────────────┼───────────────────────┘
                                   │
                                   │
BLACK-BOX 2048 TARGET              │
samples/features only              │
        │                          │
        ▼                          │
 inverse proposer                  │
 target → K patches                │
        │                          │
        ├───────────────┐          │
        ▼               ▼          │
 proposer starts    retrieval /    │
                    structured     │
                    baselines      │
        └───────┬───────┘          │
                ▼                  │
        STRUCTURED SEARCH          │
     ┌──────────────────────┐      │
     │ outer structural     │      │
     │ hypotheses           │      │
     │                      │      │
     │ inner local          │      │
     │ refinement           │      │
     │                      │      │
     │ restarts / elites /  │      │
     │ stagnation handling  │      │
     └──────────┬───────────┘      │
                ▼                  │
       compatibility scorer ◄──────┘
       + forward prediction
                │
                ▼
         bounded candidates
                │
                ▼
         native verification
                │
         ┌──────┴──────────┐
         ▼                 ▼
 verified solution     useful failure
         │                 │
         └──────┬──────────┘
                ▼
           SearchTrace
                │
       ┌────────┴─────────┐
       ▼                  ▼
 active acquisition   reachability
 / hard negatives     estimation
       │                  │
       └────────┬─────────┘
                ▼
        future retraining
```

---

# Full wavetable

```text
256 × 2048 waveform
        │
        ├──── frame 0 ── proposer ─┐
        ├──── frame 1 ── proposer ─┤
        │            ...           │
        └── frame 255 ─ proposer ──┤
                                   ▼
                           global candidate pool
                                   │
                           exact patch dedupe
                                   │
                       score each candidate against
                             all 256 targets
                                   │
                     predicted global improvement
                                   │
                             choose one patch
                                   │
                             native render once
                                   │
                       native score against all 256
                                   │
                         update all frame bests
                                   │
                         repeat until budget used
```

The global native budget belongs to the table, not independently to each frame.
