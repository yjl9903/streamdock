"""Press screen key 1 to count; bottom-right key 18 exits."""

from PIL import Image, ImageDraw

from decklet import App, Context, KeyEvent

app = App()
count = 0


def render(ctx: Context):
    image = Image.new("RGB", ctx.device.key_image_size, "#18212b")
    ImageDraw.Draw(image).text((12, 24), str(count), fill="white")
    ctx.display.set_key(1, image)


@app.on_start
async def start(ctx: Context):
    render(ctx)


@app.on_key(1)
async def increment(ctx: Context, event: KeyEvent):
    global count
    count += 1
    render(ctx)


@app.on_key(18)
async def exit_app(ctx: Context, event: KeyEvent):
    ctx.stop()
