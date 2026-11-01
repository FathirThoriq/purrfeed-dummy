import random

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

CANVAS = 512


def shrink(image, max_side=CANVAS):
    image = image.copy()
    image.thumbnail((max_side, max_side))
    return image


def grayscale(image):
    """Night-vision camera look; teaches the model that grey alone does not mean 'fake'."""
    return ImageOps.grayscale(image).convert("RGB")


def fake_print(cat, background, rnd: random.Random):
    """A cat photo shown as a paper print (white border) or on a phone screen (black bezel), placed in a room."""
    canvas = ImageOps.fit(background.convert("RGB"), (CANVAS, CANVAS))
    canvas = ImageEnhance.Brightness(canvas).enhance(rnd.uniform(0.6, 1.1))

    picture = shrink(cat, int(CANVAS * rnd.uniform(0.4, 0.75)))
    if rnd.random() < 0.5:
        picture = grayscale(picture)
    if rnd.random() < 0.5:
        border = max(6, int(max(picture.size) * rnd.uniform(0.05, 0.12)))
        tone = rnd.randint(225, 255)
        picture = ImageOps.expand(picture, border, fill=(tone, tone, tone))
    else:
        picture = ImageEnhance.Brightness(picture).enhance(rnd.uniform(1.0, 1.3))
        picture = ImageOps.expand(picture, max(4, int(max(picture.size) * rnd.uniform(0.03, 0.08))), fill=(12, 12, 14))
    picture = ImageEnhance.Contrast(picture).enhance(rnd.uniform(0.8, 1.1))

    rotated = picture.convert("RGBA").rotate(rnd.uniform(-30, 30), resample=Image.BICUBIC, expand=True)
    x = rnd.randint(0, max(0, CANVAS - rotated.width))
    y = rnd.randint(0, max(0, CANVAS - rotated.height))
    canvas.paste(rotated, (x, y), rotated)
    if rnd.random() < 0.4:
        canvas = canvas.filter(ImageFilter.GaussianBlur(rnd.uniform(0.3, 1.2)))
    return canvas
