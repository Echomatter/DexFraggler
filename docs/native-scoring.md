# Ideal targets and native scoring

Targets are mathematical sine, triangle, square and saw formulas. An anchor stores a shape name; an intermediate column stores four nonnegative blend weights whose sum is one. There are no captured cycles, editable Fourier arrays or harmonic-limit settings.

The formulas use one shared phase convention and unit peak. For a phase \(u\) in \([0,1)\), sine is \(\sin(2\pi u)\), square is positive in the first half-cycle, saw is \(1-2u\), and triangle passes through \((0,0),(1/4,1),(1/2,0),(3/4,-1),(1,0)\). At a discontinuity, numerical sampling returns the midpoint. The display uses both one-sided limits to draw vertical square/saw edges and exact triangle corners.

For blend weights \(w_j\), the ideal target is the continuous family

\[
t(\theta)=\sum_j w_j f_j(\theta).
\]

Its Fourier coefficients follow directly from those formulas. Sine has only its first harmonic. Square has \(4/(\pi k)\) at odd harmonics; saw has \(2/(\pi k)\) at every harmonic; triangle has \(8(-1)^{(k-1)/2}/(\pi^2 k^2)\) at odd harmonics. Blending combines these coefficients linearly. They are never renormalized according to a selected truncation.

## What “Band-limited match” measures

The ideal drawing remains the exact formula. Native comparison uses its orthogonal Fourier projection containing every harmonic strictly below the engine’s Nyquist frequency. At 48 kHz this means 218 harmonics for A2, 109 for A3 and 54 for A4. The model at 187.5 Hz uses 127; its 128th harmonic would lie exactly at Nyquist.

Each candidate is rendered by the native Dexed Mark I engine at velocity 100. Analysis uses all 4,096 captured samples of each held note, beginning 7,200 samples after note-on. Rendering, engine quantization, detuning, feedback and nonperiodic content remain present in the measured audio.

For centered native samples \(x_i\) and projected target samples \(t_H(\theta_i+\phi)\), the reported match is the largest positive normalized correlation over phase. Both sequences are centered over the actual capture window. The reported error is \(\sqrt{1-\mathrm{match}^2}\), equivalent to normalized residual error after the best nonnegative gain at that phase. The table’s native score is the lowest match across its three pitches; its loss is the largest squared error.

Full ideal energy and retained projection energy are also calculated analytically. The omitted high-frequency energy describes the target; it is not added as an unavoidable penalty to the native match. A band-limited match of one does not mean a finite-rate renderer reproduces an ideal discontinuity.

## Exact phase evaluation

The scorer projects the native samples onto sine and cosine bases once per capture. Dot product, target sum and target squared sum are then finite trigonometric polynomials of phase. Evaluating these polynomials gives the same finite-sample correlation as directly generating every projected target sample, without an interpolated waveform lookup table.

An FFT evaluates an initial phase grid. Adaptive subdivision uses a global second-derivative bound. For endpoint values \(f_a,f_b\), width \(d\), and \(K=Md^2/2\), the endpoint secant plus \(Kt(1-t)\) bounds the correlation above throughout \(0\le t\le1\). Its maximum is \(\max(f_a,f_b)+\max(0,K-|f_b-f_a|)^2/(4K)\), taking the correction as zero when \(K=0\). Retaining the endpoint slope makes this tighter than the former \(\max(f_a,f_b)+Md^2/8\) bound. Only intervals that could improve the best score are subdivided. The stopping tolerance is \(10^{-10}\) in correlation; Newton refinement then improves phase precision. This bound applies in exact arithmetic, with the same separate floating-point allowance in the implementation.

Native waveform previews use the fitted gain and span exactly two periods. The ideal preview is evaluated separately from the formula, using the same phase in radians. The filtered comparison is a distinct preview.

## Validation and performance

`node --test tests/ideal-targets.test.mjs tests/ideal-native-score.test.mjs` checks formulas, exact corners, Fourier coefficients, ideal energies, known phase/gain recovery and actual native captures. Five native patches cover algorithms 4, 6 and 32, feedback, fine tuning, detuning and fixed frequencies. Across 75 native pitch/target comparisons, maximum disagreement with independent sample-by-sample evaluation was **6.44×10⁻¹⁵** in score and **2.47×10⁻¹³** in preview samples. Fifteen generated projected signals recovered phase within **10⁻⁸ radians** and match within **10⁻¹⁰** of one. All six tests passed in **3.67 seconds** on the measured Windows system.

Display previews are generated only for new champions. Claims transfer scalar champion metadata; unchanged native references remain in the database without retransmitting their preview arrays. Native captures and prepared pitch transforms are reused across all 32 targets in a row. Rendering, serialization and network latency also contribute to total table throughput.

The scheduler has no “solved” score threshold. It repeatedly selects a least-visited focus cell, compares each captured patch with all 32 targets in that algorithm’s row, and saves improvements. Per-row work budgets and duplicate limits bound each visit; subsequent visits continue exploration. A test gives all 1,024 cells a score of one and verifies that every cell is still visited twice.
