#pragma once
#include "types.hpp"

namespace opxy {
// The audio contract supplies aligned, non-null, non-overlapping buffers.
// Keep compiler aliasing annotations here, outside instrument source.
using Output = i32* __restrict;
using Parameters = const i32* __restrict;
using Pitch = const u32* __restrict;
const unsigned block_frames = 64;
}
