# Shear-Wave Velocity Structure Beneath a Hypothetical Foreland Basin

<!-- FICTIONAL EXAMPLE written for this Skill's documentation and tests. The study, data and numbers do not exist. -->

## Abstract

We estimate the shear-wave velocity beneath the TOY-Basin array (42 stations, 2018-2020) by jointly inverting receiver functions and H/V spectral ratio curves. The sedimentary layer is 3.4 ± 0.3 km thick, and the Moho depth is approximately 41 km. Our results suggest that the basin floor is not uniformly flat, although the lateral variation does not exceed 1.2 km.

## 1 Introduction

Foreland basins record the interaction between crustal shortening and surface loading [1]. Previous studies have used receiver functions to image the Moho (Li et al., 2019), but they rarely account for the strong velocity contrast of the sedimentary layer [2,3]. Because shallow reverberations contaminate the converted phases, joint inversion with H/V spectral ratio (HVSR) data may be required.

In this paper we make three contributions. First, we build a 3D shear-wave velocity model, CRUST-3D, from 42 broadband stations. Second, we show that the sedimentary layer thickness correlates with the Bouguer anomaly (r = 0.78, p < 0.01). Third, we release the code at https://example.org/toy-basin and the data under DOI 10.5555/toy.2021.1.

## 2 Data and Methods

### 2.1 Data

We use waveforms from 118 teleseismic events with magnitudes of at least Mw 5.5 and epicentral distances between 30° and 90°. Only records with a signal-to-noise ratio above 2.0 were retained, which left 2,946 usable receiver functions (Fig. 1).

Figure 1. Station map and event distribution. Triangles show the 42 stations; the shaded area marks the basin boundary.

### 2.2 Joint inversion

The misfit function combines the two data types:

$$\chi^2 = \alpha \sum_i (d_i^{RF} - m_i^{RF})^2 + (1-\alpha) \sum_j (d_j^{HV} - m_j^{HV})^2 \quad (1)$$

where α is a weighting factor. We set α = 0.6 after testing values between 0.2 and 0.8, as described in Section 2.3.

Table 1. Inversion settings used in this study.

| Parameter | Value | Unit |
|---|---|---|
| Number of layers | 12 | - |
| Frequency band | 0.05-1.0 | Hz |
| Damping factor | 0.5 | - |

## 3 Results

The final model reduces the RMS misfit from 0.42 to 0.11 (Table 1). The sedimentary layer reaches a maximum thickness of 4.1 km in the south, while the Moho is no deeper than 44 km anywhere in the study area. At least 85% of the stations show a velocity inversion at depths of 2 to 6 km, which may indicate overpressured fluids.¹

## 4 Discussion

Our Moho depth of 41 km agrees with the regional average (Wang and Chen, 2020), but it is 3 km shallower than the value from gravity data [4]. We cannot exclude a bias from the assumed Vp/Vs ratio of 1.75. The results do not support a simple flexural model, and further tests with denser stations are needed.

## 5 Conclusions

We imaged the shear-wave velocity structure beneath the TOY-Basin array and found a 3.4 km thick sedimentary layer. The method is robust to noise, but it fails when fewer than 10 stations are available.

¹ Overpressure was not measured directly; the interpretation is based on velocity alone.

## References

[1] Author A. (2015). A hypothetical review of foreland basins. Journal of Imaginary Geology, 12, 1-20.

[2] Author B. (2016). Receiver functions in sedimentary basins. Journal of Imaginary Geology, 14, 21-40.
