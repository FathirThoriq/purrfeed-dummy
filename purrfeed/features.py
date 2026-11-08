# Harus sama dengan cara dataset training (Google Colab) dibuat: foto -> segmentasi rembg
# (isnet-general-use) -> crop kotak -> latar abu-abu 127 -> 224x224 -> JPEG -> MobileNetV2 (TensorFlow) -> GAP 1280.
# Ubah salah satu langkah = naikkan FEATURE_VERSION di sini dan di bundle model, lalu latih ulang.
FEATURE_VERSION = "mobilenetv2-tf-imagenet-seg127-1280"
FEATURE_DIM = 1280

import io
import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
from PIL import Image, ImageOps

IMG_SIZE = 224
BACKGROUND_RGB = (127, 127, 127)
SEGMENTATION_MODEL = "isnet-general-use"
JPEG_QUALITY = 95


def load_rgb(source):
    """Open a path, file object or PIL image as upright RGB (phone EXIF rotation applied)."""
    if isinstance(source, Image.Image):
        return source.convert("RGB")
    with Image.open(source) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def segment_crop_resize(rgb, session, remove):
    """Same steps as the training notebook: foreground mask -> square crop on grey -> 224x224. Whole image if the mask is unusable.

    Returns (image, box): box is the crop region the model looked at, normalized [x0, y0, x1, y1], or None when the
    mask was unusable and the whole frame was used."""
    rgba = remove(rgb, session=session).convert("RGBA")
    mask = (np.asarray(rgba.getchannel("A")) >= 128).astype(np.uint8) * 255
    ratio = float((mask > 0).mean())
    found = 0.005 <= ratio <= 0.995
    if not found:
        rgba = rgb.convert("RGBA")
        mask = np.full((rgb.height, rgb.width), 255, dtype=np.uint8)
    mask_img = Image.fromarray(mask, mode="L")
    box = mask_img.getbbox()
    normalized = [round(box[0] / rgb.width, 4), round(box[1] / rgb.height, 4),
                  round(box[2] / rgb.width, 4), round(box[3] / rgb.height, 4)] if found else None
    crop_rgba = rgba.crop(box)
    w, h = crop_rgba.size
    side = max(w, h)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.alpha_composite(crop_rgba, ((side - w) // 2, (side - h) // 2))
    background = Image.new("RGBA", (side, side), (*BACKGROUND_RGB, 255))
    background.alpha_composite(square)
    return background.convert("RGB").resize((IMG_SIZE, IMG_SIZE), Image.Resampling.LANCZOS), normalized


def as_training_jpeg(image):
    """The dataset was stored as JPEG; round-trip the same way so features match what the model saw."""
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


class FeatureExtractor:
    """Photo -> segmented 224x224 -> MobileNetV2 (ImageNet, frozen, TensorFlow) -> 1280-d embedding."""

    def __init__(self):
        from rembg import new_session, remove
        from tensorflow.keras.applications import MobileNetV2
        from tensorflow.keras.applications.mobilenet_v2 import preprocess_input

        self._remove = remove
        self._session = new_session(SEGMENTATION_MODEL)
        self._preprocess = preprocess_input
        self.body = MobileNetV2(weights="imagenet", include_top=False, pooling="avg",
                                input_shape=(IMG_SIZE, IMG_SIZE, 3))
        self.body.trainable = False
        self.last_boxes = []

    def prepare_with_box(self, source):
        """Segmented 224x224 RGB image plus the normalized foreground box it was cropped from."""
        segmented, box = segment_crop_resize(load_rgb(source), self._session, self._remove)
        return as_training_jpeg(segmented), box

    def prepare(self, source):
        """Segmented 224x224 RGB image for one photo (also useful to look at what the model sees)."""
        return self.prepare_with_box(source)[0]

    def __call__(self, images, batch_size=16):
        """1280-d features per image; the crop box of each image is kept in `self.last_boxes`."""
        batches, self.last_boxes = [], []
        for start in range(0, len(images), batch_size):
            prepared = [self.prepare_with_box(image) for image in images[start:start + batch_size]]
            self.last_boxes.extend(box for _, box in prepared)
            arrays = [np.asarray(image, dtype=np.float32) for image, _ in prepared]
            batch = self._preprocess(np.stack(arrays))
            batches.append(self.body.predict(batch, verbose=0))
        return np.concatenate(batches).astype(np.float32)
