"""The multimodal fusion head.

Unchanged from the 45-minute handson (car_multimodal_handson/src/model.py):
this architecture is validated and framework-agnostic
(pure PyTorch nn.Module, no Snowflake dependency) — do not redesign it.

A frozen MobileNetV3-small (Phase 5, ML Jobs) already turns each cropped frame
into a 576-d vector. What Phase 6/7 trains here is small: a per-modality
encoder and a shared regression head. The same class serves all three
ablation conditions (image / sensor / fusion) — only the branches that a
modality uses are built, so one code path answers "which modality holds the
signal?".

    image  (576) -> Linear(576,64) -> ReLU -> Dropout ┐
                                                        concat -> Linear -> ReLU -> Linear(.,1)
    sensor (C)   -> Linear(C,32)   -> ReLU  ───────────┘

C is the number of ego-dynamics channels (7 by default; see conf/train.yaml).
"""

from __future__ import annotations

from typing import Any

import torch
from torch import nn


class FusionModel(nn.Module):
    """Encoder-per-modality + shared regression head.

    Args:
        modality: "image", "sensor", or "fusion".
        image_dim: width of the frozen image feature vector.
        sensor_dim: number of ego-motion channels.
        cfg_model: the `model` section of conf/train.yaml.
    """

    def __init__(self, modality: str, image_dim: int, sensor_dim: int, cfg_model: dict[str, Any]):
        super().__init__()
        if modality not in ("image", "sensor", "fusion"):
            raise ValueError(f"modality must be image|sensor|fusion, got {modality!r}")
        self.modality = modality
        img_h = int(cfg_model["image_hidden"])
        sen_h = int(cfg_model["sensor_hidden"])
        head_h = int(cfg_model["head_hidden"])
        drop = float(cfg_model["dropout"])

        fused_dim = 0
        if modality in ("image", "fusion"):
            self.image_encoder = nn.Sequential(
                nn.Linear(image_dim, img_h), nn.ReLU(), nn.Dropout(drop)
            )
            fused_dim += img_h
        if modality in ("sensor", "fusion"):
            self.sensor_encoder = nn.Sequential(nn.Linear(sensor_dim, sen_h), nn.ReLU())
            fused_dim += sen_h

        self.head = nn.Sequential(nn.Linear(fused_dim, head_h), nn.ReLU(), nn.Linear(head_h, 1))

    def forward(
        self, image: torch.Tensor | None = None, sensor: torch.Tensor | None = None
    ) -> torch.Tensor:
        parts: list[torch.Tensor] = []
        if self.modality in ("image", "fusion"):
            if image is None:
                raise ValueError(f"modality={self.modality} needs an image input")
            parts.append(self.image_encoder(image))
        if self.modality in ("sensor", "fusion"):
            if sensor is None:
                raise ValueError(f"modality={self.modality} needs a sensor input")
            parts.append(self.sensor_encoder(sensor))
        fused = torch.cat(parts, dim=1) if len(parts) > 1 else parts[0]
        return self.head(fused).squeeze(-1)


def build_model(modality: str, image_dim: int, sensor_dim: int, cfg: dict[str, Any]) -> FusionModel:
    return FusionModel(modality, image_dim, sensor_dim, cfg["model"])


class RegistryInferenceWrapper(nn.Module):
    """Single-tensor-input adapter for Model Registry logging.

    `FusionModel.forward()` takes named `image=`/`sensor=` kwargs (needed for
    training, where a fusion batch has both). Snowflake Model Registry's
    signature inference calls `model(sample_input_data)` with a single
    positional tensor — confirmed via real error
    (`ValueError: modality=sensor needs a sensor input`, because the registry
    passed sample data positionally, which binds to `image`, not `sensor`).
    This wrapper is registry-only; it is never used for training.

    For "fusion", the single input tensor is the column-wise concatenation
    `[image_dim | sensor_dim]`, split back into the two named args internally.
    """

    def __init__(self, fusion_model: FusionModel, image_dim: int, sensor_dim: int):
        super().__init__()
        self.fusion_model = fusion_model
        self.modality = fusion_model.modality
        self.image_dim = image_dim
        self.sensor_dim = sensor_dim

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.modality == "image":
            return self.fusion_model(image=x)
        if self.modality == "sensor":
            return self.fusion_model(sensor=x)
        image, sensor = x[:, : self.image_dim], x[:, self.image_dim :]
        return self.fusion_model(image=image, sensor=sensor)

