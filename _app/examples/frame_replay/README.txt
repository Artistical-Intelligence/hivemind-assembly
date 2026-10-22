This source-known example reconstructs a small software-rendered scene in C from
an independent Python reference. It needs Python and a C compiler, not a GPU.
Input lines are: frame_index dx dy. Each move is applied before that frame is
captured. Coordinates are clamped to keep the 2x2 sprite inside a 16x16 scene.
Frames are tightly packed RGBA8, top row first, at a declared 60 frames/second.
The frame rate labels sampling positions; this example does not measure real time.

In HA, authorize the supplied native examples, then create the frame replay
example. Run tests, change "tick == frame" to "tick == frame - 1" in candidate.c,
save, and run again. For the supplied movements, final.bin still matches but
intermediate frames fail. Click Inspect captures, choose frames.rgba and scrub
both captures together or jump to the first failing frame. Download either raw
capture from its preview to inspect all frames with external tools. The original, cases
and comparison thresholds are pinned independently of editable workspace files.

Command-line execution from the HA root:
python _app/launch.py test-programs --suite _app/examples/frame_replay/suite.json --workspace _app/examples/frame_replay --compiler clang --allow-native

frames.rgba uses the FFmpeg rawvideo layout. To inspect a retained raw capture
outside HA, with FFmpeg tools installed:
ffplay -f rawvideo -pixel_format rgba -video_size 16x16 -framerate 60 candidate-frames.rgba

This verifies sampled software output and input ordering, not arbitrary games,
graphics driver behavior, display timing or all possible input sequences.
