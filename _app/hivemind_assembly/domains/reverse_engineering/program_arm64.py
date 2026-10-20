"""Trusted freestanding Linux AArch64 entry and syscall stubs.

Numbers follow Linux's asm-generic UAPI. Stubs do not grant runtime support:
the static replay dispatcher admits only streams, exit and an explicit clock.
Other effects fail closed rather than reaching the host.
"""

# Canonical operation IDs used by HA's existing Linux dispatcher. Qiling still
# receives the original ARM syscall number and supplies the ABI-specific handler.
QILING_OPERATIONS = {
    63: 0, 64: 1, 56: 257, 57: 3, 62: 8, 222: 9, 226: 10,
    215: 11, 214: 12, 67: 17, 68: 18, 93: 60, 94: 231,
    17: 79, 113: 228, 278: 318, 79: 262, 80: 5,
    96: 218, 99: 273, 293: 334, 261: 302,
}


def qiling_operation(number, args):
    """Normalize CWD-only *at forms to existing, guarded Qiling operations.

    Qiling 1.4.6 lacks mkdirat/renameat and ignores unlinkat's removal flag.
    Reuse its existing mkdir/rename/unlink/rmdir handlers after the same path
    guards. No host descriptors or unknown flags are accepted.
    """
    from hivemind_assembly.core.common import Blocked

    handler = None
    if number in (34, 35, 38):
        if args[0] & 0xFFFFFFFF != 0xFFFFFF9C or (
            number == 38 and args[2] & 0xFFFFFFFF != 0xFFFFFF9C
        ):
            raise Blocked("unsupported_directory_fd")
        if number == 34:
            from qiling.os.posix.syscall.stat import ql_syscall_mkdir
            return 83, [args[1], args[2], 0, 0, 0, 0], (ql_syscall_mkdir, 2)
        if number == 38:
            from qiling.os.posix.syscall.fcntl import ql_syscall_rename
            return 82, [args[1], args[3], 0, 0, 0, 0], (ql_syscall_rename, 2)
        if args[2] == 0:
            from qiling.os.posix.syscall.unistd import ql_syscall_unlink
            return 87, [args[1], 0, 0, 0, 0, 0], (ql_syscall_unlink, 1)
        if args[2] == 512:
            from qiling.os.posix.syscall.stat import ql_syscall_rmdir
            return 84, [args[1], 0, 0, 0, 0, 0], (ql_syscall_rmdir, 1)
        raise Blocked("unsupported_unlink_flags")
    return QILING_OPERATIONS.get(number), args, handler


SYSCALL_RUNTIME = r"""
static long ha_call6(long n,long a,long b,long c,long d,long e,long f){
    register long x8 __asm__("x8")=n;
    register long x0 __asm__("x0")=a;
    register long x1 __asm__("x1")=b;
    register long x2 __asm__("x2")=c;
    register long x3 __asm__("x3")=d;
    register long x4 __asm__("x4")=e;
    register long x5 __asm__("x5")=f;
    __asm__ volatile("svc #0":"+r"(x0):"r"(x8),"r"(x1),"r"(x2),"r"(x3),"r"(x4),"r"(x5):"memory","cc");
    return x0;
}
long ha_read(void *p,ha_size n){return ha_call6(63,0,(long)p,n,0,0,0);}
long ha_write(const void *p,ha_size n){return ha_call6(64,1,(long)p,n,0,0,0);}
void ha_exit(int n){ha_call6(93,n,0,0,0,0,0);__builtin_unreachable();}
long ha_open(const char *p,long f,long m){return ha_call6(56,-100,(long)p,f,m,0,0);}
long ha_mkdir(const char *p,long m){return ha_call6(34,-100,(long)p,m,0,0,0);}
long ha_rmdir(const char *p){return ha_call6(35,-100,(long)p,512,0,0,0);}
long ha_remove(const char *p){return ha_call6(35,-100,(long)p,0,0,0,0);}
long ha_rename(const char *a,const char *b){return ha_call6(38,-100,(long)a,-100,(long)b,0,0);}
long ha_clock(long id,long *s,long *ns){long t[2];long r=ha_call6(113,id,(long)t,0,0,0,0);if(!r){*s=t[0];*ns=t[1];}return r;}
long ha_random(void *p,ha_size n,long f){return ha_call6(278,(long)p,n,f,0,0,0);}
long ha_close(long f){return ha_call6(57,f,0,0,0,0,0);}
long ha_seek(long f,long o,long w){return ha_call6(62,f,o,w,0,0,0);}
long ha_file_read(long f,void *p,ha_size n){return ha_call6(63,f,(long)p,n,0,0,0);}
long ha_file_write(long f,const void *p,ha_size n){return ha_call6(64,f,(long)p,n,0,0,0);}
void *ha_map(ha_size n){return (void*)ha_call6(222,0,n,3,34,-1,0);}
long ha_unmap(void *p,ha_size n){return ha_call6(215,(long)p,n,0,0,0,0);}
__attribute__((naked)) void _start(void){__asm__ volatile("mov x0, sp; bl ha_boot; bl ha_exit; brk #0");}
"""
