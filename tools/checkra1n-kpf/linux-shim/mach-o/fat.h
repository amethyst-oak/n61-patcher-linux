#pragma once
#include <stdint.h>
#include <mach-o/loader.h>
#define FAT_MAGIC 0xcafebabeu
#define FAT_CIGAM 0xbebafecau
#define CPU_TYPE_ARM64 0x0100000c
struct fat_header { uint32_t magic, nfat_arch; };
struct fat_arch { cpu_type_t cputype; cpu_subtype_t cpusubtype; uint32_t offset, size, align; };
