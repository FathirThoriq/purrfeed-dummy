import numpy as np
import torch
from PIL import Image, ImageOps
from torch import nn
from torchvision import models


def load_rgb(source):
    """Open a path, file object or PIL image as upright RGB (phone EXIF rotation applied)."""
    if isinstance(source, Image.Image):
        return source.convert("RGB")
    with Image.open(source) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


class FeatureExtractor:
    """MobileNetV2 pretrained on ImageNet, without its classifier: image -> 1280-d embedding."""

    def __init__(self):
        weights = models.MobileNet_V2_Weights.IMAGENET1K_V2
        network = models.mobilenet_v2(weights=weights).eval()
        self.body = nn.Sequential(network.features, nn.AdaptiveAvgPool2d(1), nn.Flatten())
        self.transform = weights.transforms()

    @torch.no_grad()
    def __call__(self, images, batch_size=32):
        batches = []
        for start in range(0, len(images), batch_size):
            tensors = [self.transform(load_rgb(image)) for image in images[start:start + batch_size]]
            batches.append(self.body(torch.stack(tensors)).numpy())
        return np.concatenate(batches).astype(np.float32)
