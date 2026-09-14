# Analytic level fitting

`public/core.mjs` propagates six forward derivatives through the smooth oscillator network. The derivative includes the piecewise relaxed output-level law, nested phase modulation, carrier gain and both delayed feedback samples.

The renderer advances every phase with the same per-sample recurrence. During warmup, it skips only sine evaluations outside the transitive dependencies of the feedback source. Those operators cannot affect persistent feedback state. Measured samples and carrier components remain bit-for-bit equal to the unpruned renderer.

`fitLevels` removes nuisance DC and fitted gain directions from the Jacobian, builds a damped Gauss–Newton system, bounds the shared level displacement to eight and rounds to legal operator levels. The fitted patch is only a proposal; model and native acceptance remain independent and monotonic.

Muted levels are locally flat, so discrete proposals continue to activate operators. Nonfinite feedback tangents return an unchanged proposal rather than contaminating the solve.

`tests/jacobian.test.mjs` covers every algorithm and feedback amount, carrier components, fixed oscillators, detuning and central finite differences. Across 768 derivative comparisons, maximum relative error was 3.14e-9. Individual proposals can fail to improve, and the acceptance test rejects them.
