/* Stand-in for the STM32 HAL so the LXR sound engine builds on the Pi (Linux, gcc). */
#ifndef CONSOLE_SHIM_HAL_H
#define CONSOLE_SHIM_HAL_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <math.h>
#define __IO volatile
#define IN_ITCM_RAM
static inline int32_t __SSAT(int32_t v, int bits) {
    int32_t hi = (1 << (bits - 1)) - 1, lo = -(1 << (bits - 1));
    return v > hi ? hi : (v < lo ? lo : v);
}
static inline uint32_t __USAT(int32_t v, int bits) {
    int32_t hi = (1 << bits) - 1;
    return v > hi ? hi : (v < 0 ? 0 : v);
}
static inline uint32_t __QADD16(uint32_t a, uint32_t b) {   /* two saturating 16-bit adds */
    int32_t lo = __SSAT((int16_t)(a & 0xffff) + (int16_t)(b & 0xffff), 16);
    int32_t hi = __SSAT((int16_t)(a >> 16) + (int16_t)(b >> 16), 16);
    return ((uint32_t)(uint16_t)hi << 16) | (uint16_t)lo;
}
static inline uint32_t __QSUB16(uint32_t a, uint32_t b) {   /* two saturating 16-bit subtracts */
    int32_t lo = __SSAT((int16_t)(a & 0xffff) - (int16_t)(b & 0xffff), 16);
    int32_t hi = __SSAT((int16_t)(a >> 16) - (int16_t)(b >> 16), 16);
    return ((uint32_t)(uint16_t)hi << 16) | (uint16_t)lo;
}
#define __PKHBT(a, b, shift) ((((uint32_t)(a)) & 0x0000ffffu) | ((((uint32_t)(b)) << (shift)) & 0xffff0000u))
static inline uint32_t __CLZ(uint32_t v) { return v ? __builtin_clz(v) : 32; }
#if !defined(__aarch64__) && !defined(__arm__)
#define __fp16 _Float16                 /* half floats: native on the Pi's ARM, _Float16 elsewhere (for testing) */
#endif
#define __STATIC_INLINE static inline
typedef struct { uint32_t dummy; } RNG_HandleTypeDef;
static inline uint32_t HAL_RNG_GetRandomNumber(RNG_HandleTypeDef *h) {   /* the chip's random-number unit -> xorshift */
    static uint32_t s = 2463534242u;
    (void)h;
    s ^= s << 13; s ^= s >> 17; s ^= s << 5;
    return s;
}
typedef struct { volatile uint32_t CYCCNT, CTRL; } DWT_Type;
extern DWT_Type console_dwt;
#define DWT (&console_dwt)
static inline uint32_t HAL_RCC_GetHCLKFreq(void) { return 216000000u; }
static inline uint32_t HAL_GetTick(void) { return 0; }
typedef struct { volatile uint32_t IDR; } GPIO_TypeDef;   /* the LXR's output-jack switches: all "plugged in" */
extern GPIO_TypeDef console_gpio;
#define switch_l1_GPIO_Port (&console_gpio)
#define switch_r1_GPIO_Port (&console_gpio)
#define switch_l2_GPIO_Port (&console_gpio)
#define switch_r2_GPIO_Port (&console_gpio)
#define switch_l1_Pin 1u
#define switch_r1_Pin 2u
#define switch_l2_Pin 4u
#define switch_r2_Pin 8u
#define __disable_irq()
#define __enable_irq()
#endif
