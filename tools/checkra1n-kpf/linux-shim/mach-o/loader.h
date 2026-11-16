/* Minimal Mach-O definitions so the host KPF builds on Linux (layout from Apple's loader.h). */
#pragma once
#include <stdint.h>
typedef int cpu_type_t;
typedef int cpu_subtype_t;
typedef int vm_prot_t;
#define MH_MAGIC_64 0xfeedfacfu
#define LC_SEGMENT_64 0x19u
#define LC_UNIXTHREAD 0x5u
#define VM_PROT_READ 1
#define VM_PROT_WRITE 2
#define VM_PROT_EXECUTE 4
struct mach_header_64 { uint32_t magic; cpu_type_t cputype; cpu_subtype_t cpusubtype;
    uint32_t filetype, ncmds, sizeofcmds, flags, reserved; };
struct load_command { uint32_t cmd, cmdsize; };
struct segment_command_64 { uint32_t cmd, cmdsize; char segname[16];
    uint64_t vmaddr, vmsize, fileoff, filesize; vm_prot_t maxprot, initprot; uint32_t nsects, flags; };
struct section_64 { char sectname[16], segname[16]; uint64_t addr, size;
    uint32_t offset, align, reloff, nreloc, flags, reserved1, reserved2, reserved3; };
struct thread_command { uint32_t cmd, cmdsize; };
