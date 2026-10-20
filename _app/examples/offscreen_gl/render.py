"""Source-known EGL/OpenGL fixture: no desktop, window, browser or GPU needed.

Writes bottom-up RGBA bytes. Failure to create a real context is a failed probe,
never replaced with a generated image. Intended for Mesa Linux runners.
"""

import ctypes as c
import ctypes.util
import json
import os
from pathlib import Path

os.environ["LIBGL_ALWAYS_SOFTWARE"] = "true"


def bind(lib, name, restype, *args):
    fn = getattr(lib, name)
    fn.restype, fn.argtypes = restype, list(args)
    return fn


def render():
    egl = c.CDLL(ctypes.util.find_library("EGL") or "libEGL.so.1")
    gl = c.CDLL(ctypes.util.find_library("GL") or "libGL.so.1")
    ptr, integer = c.c_void_p, c.c_int
    get_display = bind(
        egl, "eglGetPlatformDisplay", ptr, c.c_uint, ptr, c.POINTER(c.c_ssize_t)
    )
    initialize = bind(
        egl, "eglInitialize", c.c_uint, ptr, c.POINTER(integer), c.POINTER(integer)
    )
    choose = bind(
        egl,
        "eglChooseConfig",
        c.c_uint,
        ptr,
        c.POINTER(integer),
        c.POINTER(ptr),
        integer,
        c.POINTER(integer),
    )
    bind_api = bind(egl, "eglBindAPI", c.c_uint, c.c_uint)
    context_fn = bind(egl, "eglCreateContext", ptr, ptr, ptr, ptr, c.POINTER(integer))
    surface_fn = bind(egl, "eglCreatePbufferSurface", ptr, ptr, ptr, c.POINTER(integer))
    current = bind(egl, "eglMakeCurrent", c.c_uint, ptr, ptr, ptr, ptr)
    terminate = bind(egl, "eglTerminate", c.c_uint, ptr)
    destroy_context = bind(egl, "eglDestroyContext", c.c_uint, ptr, ptr)
    destroy_surface = bind(egl, "eglDestroySurface", c.c_uint, ptr, ptr)
    display = get_display(0x31DD, None, None)  # EGL_PLATFORM_SURFACELESS_MESA
    major, minor = integer(), integer()
    context, surface = None, None
    try:
        if not display or not initialize(display, c.byref(major), c.byref(minor)):
            raise RuntimeError("Surfaceless EGL initialization unavailable")
        attributes = (integer * 13)(
            0x3033, 1, 0x3040, 8, 0x3024, 8, 0x3023, 8, 0x3022, 8, 0x3021, 8, 0x3038
        )
        config, count = ptr(), integer()
        if (
            not choose(display, attributes, c.byref(config), 1, c.byref(count))
            or count.value < 1
            or not bind_api(0x30A2)
        ):
            raise RuntimeError("OpenGL RGBA8 pbuffer configuration unavailable")
        context = context_fn(display, config, None, (integer * 1)(0x3038))
        surface = surface_fn(
            display, config, (integer * 5)(0x3057, 16, 0x3056, 16, 0x3038)
        )
        if (
            not context
            or not surface
            or not current(display, surface, surface, context)
        ):
            raise RuntimeError("Cannot activate offscreen OpenGL context")
        clear_color = bind(
            gl, "glClearColor", None, c.c_float, c.c_float, c.c_float, c.c_float
        )
        clear = bind(gl, "glClear", None, c.c_uint)
        enable = bind(gl, "glEnable", None, c.c_uint)
        scissor = bind(gl, "glScissor", None, integer, integer, integer, integer)
        read = bind(
            gl,
            "glReadPixels",
            None,
            integer,
            integer,
            integer,
            integer,
            c.c_uint,
            c.c_uint,
            ptr,
        )
        error = bind(gl, "glGetError", c.c_uint)
        get_string = bind(gl, "glGetString", c.c_char_p, c.c_uint)
        clear_color(0, 0, 0, 1)
        clear(0x4000)
        enable(0x0C11)
        for x, y, color in (
            (0, 0, (1, 0, 0)),
            (8, 0, (0, 1, 0)),
            (0, 8, (0, 0, 1)),
            (8, 8, (1, 1, 1)),
        ):
            scissor(x, y, 8, 8)
            clear_color(*color, 1)
            clear(0x4000)
        pixels = (c.c_ubyte * (16 * 16 * 4))()
        read(0, 0, 16, 16, 0x1908, 0x1401, pixels)
        if error() != 0:
            raise RuntimeError("OpenGL reported an error")
        Path("frame.rgba").write_bytes(bytes(pixels))
        Path("renderer.json").write_text(
            json.dumps(
                {
                    "renderer": get_string(0x1F01).decode(),
                    "version": get_string(0x1F02).decode(),
                    "egl": [major.value, minor.value],
                }
            )
        )
    finally:
        if display:
            current(display, None, None, None)
            if surface:
                destroy_surface(display, surface)
            if context:
                destroy_context(display, context)
            terminate(display)


if __name__ == "__main__":
    render()
