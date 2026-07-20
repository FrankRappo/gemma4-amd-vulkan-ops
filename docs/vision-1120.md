# Gemma 4 high-detail Vision profile

## Configuration

The high-detail profile uses the model-supported adaptive visual token range:

```ini
VISION_MIN_TOKENS=280
VISION_MAX_TOKENS=1120
VISION_BATCH_SIZE=1280
VISION_UBATCH_SIZE=1280
VISION_MTMD_BATCH_MAX_TOKENS=1280
```

The micro-batch and multimodal batch limits must be at least the maximum image
token count. Gemma image attention is non-causal; splitting an image chunk into
an undersized micro-batch can abort evaluation.

## Measured trade-off

A same-image A/B test corrected a small OCR date that the 280-token profile read
incorrectly. Dense screenshot latency increased from 20.33 s to 30.54 s. The
measured service-cgroup memory delta was about 502 MiB, swap did not increase,
and host memory remained comfortably available. These numbers are deployment
specific and should be re-measured after changing model, projector, runtime, or
driver.

## Rollback

Set both visual limits to 280 and all three batch limits to 512, restart the
primary service, then repeat the same image fixture.
