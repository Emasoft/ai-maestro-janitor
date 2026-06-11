---
description: a logistic regression failure on the training data
tags: [ml, regression]
---
# Logistic regression

The model diverged; this was a logistic regression failure, not a data issue.[^2]

## Notes and lessons learned

[^2]: the logistic regression failure was caused by an unscaled feature column;
  standardize the inputs before fitting to avoid the divergence.
