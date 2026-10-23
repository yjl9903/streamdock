import asyncio
import unittest
from io import BytesIO

from PIL import Image

from decklet import Display
from decklet.rendering import encode_key


class DisplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_images_are_snapshots_and_partial_updates_merge(self):
        display = Display()
        image = Image.new("RGB", (64, 64), "red")
        display.set_key(1, image)
        image.paste("blue", (0, 0, 64, 64))
        display.set_key(2, image)
        display.set_key(2, Image.new("RGB", (64, 64), "green"))
        batch = display._pending()
        self.assertEqual(set(batch), {1, 2})
        self.assertEqual(batch[1][1].getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(batch[2][1].getpixel((0, 0)), (0, 128, 0))

    async def test_inflight_ack_does_not_lose_newer_updates_and_flush_waits(self):
        display = Display()
        display.set_key(1, Image.new("RGB", (64, 64), "red"))
        old = display._pending()
        display.set_key(1, Image.new("RGB", (64, 64), "blue"))
        waiter = asyncio.create_task(display.flush())
        display._acknowledge(old)
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        display._acknowledge(display._pending())
        await asyncio.wait_for(waiter, 1)
        self.assertEqual(display._pending(), {})
        display._reconnect()
        self.assertEqual(set(display._pending()), {1})

    async def test_canvas_gap_and_jpeg_validation_are_atomic(self):
        display = Display()
        canvas = Image.new("RGB", (352, 208), "red")
        canvas.paste("blue", (72, 0, 136, 64))
        display.set_canvas(canvas, gap=8)
        batch = display._pending()
        self.assertEqual(batch[2][1].getpixel((0, 0)), (0, 0, 255))
        revision = display._revision
        with self.assertRaises(ValueError):
            display.set_jpegs([(1, encode_key(Image.new("RGB", (64, 64)))), (16, b"bad")])
        self.assertEqual(display._revision, revision)
        for key in (0, 16, 18, True):
            with self.assertRaises(ValueError):
                display.set_key(key, Image.new("RGB", (64, 64)))
        with self.assertRaises(ValueError):
            display.set_key(1, Image.new("RGB", (32, 32)))
        with self.assertRaises(ValueError):
            display.set_canvas(canvas, gap=-1)
        png = BytesIO()
        Image.new("RGB", (64, 64)).save(png, "PNG")
        with self.assertRaises(ValueError):
            display.set_jpegs([(1, png.getvalue())])

    async def test_shutdown_wakes_pending_flush(self):
        display = Display()
        display.clear()
        waiter = asyncio.create_task(display.flush())
        await asyncio.sleep(0)
        display._close()
        with self.assertRaisesRegex(RuntimeError, "关闭"):
            await waiter
