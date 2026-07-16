# ITU-R validation examples (installation anchors)

Official software-validation examples for Recommendations **ITU-R P.452-18**
and **ITU-R P.2001**, as distributed with the official reference
implementations (github.com/eeveetza/Py452 and /Py2001, maintained at the
Swiss Federal Office of Communications for ITU-R SG3). They exist precisely
so an installation can prove it reproduces the Recommendation.

`tools/validate_predictions.py` replays them through THIS machine's installed
reference engines and `tests/test_itu_validation.py` gates the deviation at
the official tolerance (1e-6 dB). The P.2001 results file is a uniform
subsample (~45 of 2215 rows spanning every frequency and time-percentage
decade) to keep the repository lean; the full suites pass identically.
