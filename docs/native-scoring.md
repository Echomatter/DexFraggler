# Native scoring

`runner/measurement.mjs` exports `prepareAudio(audio, note)`, `scorePrepared(context, target, harmonics)` and the compatible `measuredScore(audio, target, note, harmonics)`. Prepared contexts retain immutable capture data. `Reference.scoreMany` shares those contexts across the row.

The target is a 32,768-point linearly interpolated Fourier table. Measurement retains all 4,096 captured samples, the three native pitches, 128 coarse phase locations and 28 refinement iterations.

For a capture, projecting centered audio onto sine/cosine bases at harmonics 1–64 makes continuous Fourier dot products available in O(H). The interpolation second-derivative bound relates that continuous target to the actual sampled interpolant:

```
epsilon <= (2*pi/32768)^2 / 8 * sum_k k^2 * hypot(sin[k], cos[k])
abs(correlation_exact - correlation_projected)
    <= sqrt(N / target_centered_energy_exact) * epsilon
```

Target means and centered energies at coarse positions are cached exactly. A phase can be skipped only when its upper correlation bound is below another phase's lower bound, with a conservative floating-point allowance. All possible winners are checked in their defined order against the sampled objective. All refinement iterations use that same objective. Approximate projections never supply returned scores.

The native wrapper uses an exact full-SysEx cache key, a bounded 16-entry LRU and concurrent-request deduplication. Captures cannot be reused for different encoded patches. Optional `preview:false` omits display arrays only. The scheduler requests full previews for saved results.

Development benchmarks compared 1,059 native/pitch/target combinations: maximum score difference 2.22e-16, maximum relative-error difference 1.53e-15 and maximum preview-sample difference 8.88e-16. An alternating-order benchmark of 32-column rows measured a median 6.51× scoring speedup. These are scorer measurements; HTTP and native rendering also contribute to total table time.

`tests/native-score.test.mjs` regenerates native captures and checks score, error, phase and preview agreement against `tests/fixtures/measurement-baseline.mjs`, as well as capture caching and invalid-input recovery. The reference objective is retained as a test oracle, outside the public app.
