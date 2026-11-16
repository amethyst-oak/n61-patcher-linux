#pragma once
#include <stdint.h>
#include <mach-o/loader.h>
typedef int kern_return_t;
typedef int boolean_t;
typedef void *vm_map_t;
typedef uint64_t mach_vm_address_t;
typedef uint64_t mach_vm_size_t;
#define KERN_SUCCESS 0
#define MAP_JIT 0
#define ARM_THREAD_STATE64 6
typedef struct { uint64_t __x[29], __fp, __lr, __sp, __pc; uint32_t __cpsr, __pad; } _STRUCT_ARM_THREAD_STATE64;
